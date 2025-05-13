use base64::{engine::general_purpose, Engine as _};
use clap::Parser;
use glob::glob;
use log::{debug, error, info};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::env;
use std::error::Error;
use std::fs;
use std::path::{Path, PathBuf};

const PROMPT: &str = r#"
1). When is the document dated (if any)?
2). What is the document? Eg, invoice, receipt, report etc.
3). What should the document title be (if any)?
4). What would be a good filename for this document, use the format {YYYYMMDD}-{title}-{category}.
5). If it makes sense, take inspiration from the original filename ({original_filename}) to come up with a better title.

Output your response as JSON, eg:
{
    "date": "2021-12-24",  // Use the format YYYY-MM-DD
    "category": "invoice"  // Keep the category in lowercase
    "filename": "20211224-dan-murphys-invoice"  // All lowercase, no spaces. Words separated by hyphens.
}
"#;

#[derive(Debug, PartialEq, serde::Deserialize)]
struct DocumentIntelligence {
    date: Option<String>,
    category: Option<String>,
    filename: Option<String>,
}

#[derive(Serialize, Debug)]
struct InputFilePart<'a> {
    #[serde(rename = "type")]
    type_field: &'static str,
    filename: &'a str,
    file_data: String, // Will be "data:application/pdf;base64,..."
}

#[derive(Serialize, Debug)]
struct InputTextPart<'a> {
    #[serde(rename = "type")]
    type_field: &'static str,
    text: &'a str,
}

#[derive(Serialize, Debug)]
#[serde(untagged)] // To allow either InputFilePart or InputTextPart
enum ContentPart<'a> {
    File(InputFilePart<'a>),
    Text(InputTextPart<'a>),
}

#[derive(Serialize, Debug)]
struct InputItem<'a> {
    role: &'static str,
    content: Vec<ContentPart<'a>>,
}

#[derive(Serialize, Debug)]
struct CustomApiRequest<'a> {
    model: &'a str,
    input: Vec<InputItem<'a>>,
    // Add other common parameters if needed, e.g., max_tokens, temperature
    // For simplicity, starting with model and input.
    // max_tokens: Option<u32>,
    // temperature: Option<f32>,
}

#[derive(Deserialize, Debug)]
struct CustomApiResponse {
    output: Option<Vec<OutputItem>>,
}

#[derive(Deserialize, Debug)]
struct OutputItem {
    content: Option<Vec<OutputContentPart>>,
}

#[derive(Deserialize, Debug)]
struct OutputContentPart {
    text: Option<String>,
}

#[derive(Deserialize, Debug)]
struct OpenAiErrorResponseDetail {
    message: String,
    #[serde(rename = "type")]
    error_type: String,
    param: Option<String>,
    code: Option<String>,
}

#[derive(Deserialize, Debug)]
struct OpenAiErrorResponse {
    error: OpenAiErrorResponseDetail,
}

#[derive(Parser, Debug)]
#[command(version, about)]
struct Args {
    #[arg(short, long, default_value = "")]
    glob_pattern: String,
    #[arg(short, long, default_value = "gpt-4o")]
    model: String,
    #[arg(short, long, action)]
    dry_run: bool,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    colog::init();
    let args = Args::parse();

    let final_glob_pattern = if args.glob_pattern.is_empty() {
        info!("Command-line glob_pattern is blank. Attempting to use PAPERSMITH_GLOB_PATTERN environment variable.");
        match std::env::var("PAPERSMITH_GLOB_PATTERN") {
            Ok(env_var_value) if !env_var_value.is_empty() => {
                env_var_value // Use env var
            }
            Ok(_) => {
                // Env var is present but empty
                return Err("Command-line glob_pattern was blank and PAPERSMITH_GLOB_PATTERN environment variable is also blank.".into());
            }
            Err(_) => {
                // Env var not set
                return Err("Command-line glob_pattern was blank and PAPERSMITH_GLOB_PATTERN environment variable is not set.".into());
            }
        }
    } else {
        args.glob_pattern // Use CLI arg
    };

    let mut files_to_process: Vec<String> = Vec::new();
    let filename_regex = Regex::new(r"^\d{8}.*\.pdf$")?;
    for entry in glob(&final_glob_pattern)? {
        let path_buf: PathBuf = entry?;
        let pdf_path_str = path_buf
            .to_str()
            .ok_or_else(|| format!("Path contains invalid UTF-8: {:?}", path_buf))?;

        let current_filename_osstr = path_buf
            .file_name()
            .ok_or_else(|| format!("Failed to get file name for path: {:?}", path_buf))?;
        let current_filename = current_filename_osstr
            .to_str()
            .ok_or_else(|| format!("File name {:?} is not valid UTF-8", current_filename_osstr))?;

        // If it starts with 8 digits and ends with .pdf, skip it
        if filename_regex.is_match(current_filename) {
            info!("Skipping {}", current_filename);
            continue;
        }

        files_to_process.push(pdf_path_str.to_string());
    }

    for pdf_path in files_to_process {
        let path_obj = Path::new(&pdf_path);
        let current_filename_osstr = path_obj
            .file_name()
            .ok_or_else(|| format!("Failed to get file name for path: {}", pdf_path))?;
        let current_filename = current_filename_osstr.to_str().ok_or_else(|| {
            format!(
                "File name {:?} from path {} is not valid UTF-8",
                current_filename_osstr, pdf_path
            )
        })?;

        info!("Processing {}", current_filename);

        let document_intelligence =
            get_document_intelligence(&pdf_path, args.model.as_str()).await?;

        if let Some(name_part) = document_intelligence.filename {
            let filename_suggestion = format!("{}.pdf", name_part);

            if args.dry_run {
                info!(
                    "Not renaming {} to {} (dry-run)",
                    current_filename, filename_suggestion
                );
            } else {
                let new_path = path_obj.with_file_name(&filename_suggestion);
                fs::rename(&pdf_path, new_path)?;

                info!("Renamed {} to {}", current_filename, filename_suggestion);
            }
        } else {
            info!(
                "LLM did not suggest a filename for {}. Skipping rename.",
                current_filename
            );
        }
    }

    Ok(())
}

async fn get_document_intelligence(
    pdf_path: &str,
    model: &str,
) -> Result<DocumentIntelligence, Box<dyn Error>> {
    let pdf_data =
        fs::read(pdf_path).map_err(|e| format!("Failed to read PDF file {}: {}", pdf_path, e))?;

    if pdf_data.is_empty() {
        return Err(format!("PDF file {} is empty.", pdf_path).into());
    }

    let base64_pdf = general_purpose::STANDARD.encode(&pdf_data);
    let file_data_uri = format!("data:application/pdf;base64,{}", base64_pdf);

    let pdf_filename = Path::new(pdf_path)
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("document.pdf");

    let api_key = env::var("PAPERSMITH_OPENAI_API_KEY")
        .map_err(|_| "PAPERSMITH_OPENAI_API_KEY environment variable not set")?;

    let http_client = reqwest::Client::new();

    let prompt_text = PROMPT.replace("{original_filename}", pdf_filename);
    let request_payload = CustomApiRequest {
        model,
        input: vec![InputItem {
            role: "user",
            content: vec![
                ContentPart::File(InputFilePart {
                    type_field: "input_file",
                    filename: pdf_filename,
                    file_data: file_data_uri,
                }),
                ContentPart::Text(InputTextPart {
                    type_field: "input_text",
                    text: &prompt_text,
                }),
            ],
        }],
    };

    const API_PATH: &str = "/v1/responses";
    let api_url = format!("https://api.openai.com{}", API_PATH);

    info!("Sending custom request to {} with model {}", api_url, model);

    // Convert payload to string for debug logging, handle potential error
    match serde_json::to_string_pretty(&request_payload) {
        Ok(payload_str) => debug!("Request payload: {}", payload_str),
        Err(e) => debug!("Failed to serialize request payload for logging: {}", e),
    }

    let res = http_client
        .post(&api_url)
        .bearer_auth(api_key)
        .json(&request_payload)
        .send()
        .await?;

    let response_status = res.status();
    let response_text = res.text().await?;
    debug!("API Response Status: {}", response_status);
    debug!("API Response Body: {}", response_text);

    if !response_status.is_success() {
        match serde_json::from_str::<OpenAiErrorResponse>(&response_text) {
            Ok(err_resp) => {
                error!(
                    "OpenAI API Error: Type: {}, Message: {}, Code: {:?}, Param: {:?}",
                    err_resp.error.error_type,
                    err_resp.error.message,
                    err_resp.error.code,
                    err_resp.error.param
                );
                return Err(format!(
                    "OpenAI API error ({}): {}",
                    err_resp.error.error_type, err_resp.error.message
                )
                .into());
            }
            Err(_) => {
                // Fallback if error parsing fails
                error!(
                    "API request failed with status {} and body: {}",
                    response_status, response_text
                );
                return Err(format!(
                    "API request failed with status {}: {}",
                    response_status, response_text
                )
                .into());
            }
        }
    }

    // Assuming success, parse into CustomApiResponse
    let response: CustomApiResponse = serde_json::from_str(&response_text).map_err(|e| {
        error!(
            "Failed to parse successful API response: {}. Body: {}",
            e,
            response_text // Log the original String here
        );
        format!(
            "Failed to parse successful API response: {}. Body: {}",
            e,
            response_text // Log the original String here
        )
    })?;

    // Extract the text from the nested structure
    let content_str = response
        .output
        .as_ref()
        .and_then(|outputs| outputs.first())
        .and_then(|first_output| first_output.content.as_ref())
        .and_then(|contents| contents.first())
        .and_then(|first_content| first_content.text.as_ref())
        .cloned() // Clone the Option<String> to get String or None
        .ok_or_else(|| {
            error!(
                "Failed to extract text from API response structure. Full response: {}",
                response_text
            );
            "Failed to extract text from API response structure".to_string()
        })?;

    let repaired_json_str = repair_json::repair(
        content_str
            .replace("```json", "")
            .replace("```", "")
            .as_str(),
    )
    .map_err(|e_str| {
        std::io::Error::new(
            std::io::ErrorKind::Other,
            format!("JSON repair failed for {}: {}", pdf_path, e_str),
        )
    })?;

    let document_intelligence: DocumentIntelligence = serde_json::from_str(&repaired_json_str)
        .map_err(|e_serde| {
            std::io::Error::new(
                std::io::ErrorKind::Other,
                format!(
                    "Failed to parse JSON for {} ({}): {}. Repaired JSON: '{}'",
                    pdf_path, e_serde, content_str, repaired_json_str
                ),
            )
        })?;

    Ok(document_intelligence)
}
