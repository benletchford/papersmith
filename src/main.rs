use async_openai::{
    types::{
        ChatCompletionRequestMessageContentPartImageArgs,
        ChatCompletionRequestMessageContentPartTextArgs, ChatCompletionRequestUserMessageArgs,
        CreateChatCompletionRequestArgs, ImageDetail, ImageUrlArgs,
    },
    Client,
};
use base64::{engine::general_purpose, Engine as _};
use clap::Parser;
use dotenvy::dotenv;
use glob::glob;
use image::{DynamicImage, GenericImage, ImageFormat};
use log::{debug, info};
use pdf2image::{RenderOptionsBuilder, DPI, PDF};
use regex::Regex;
use std::error::Error;
use std::fs;
use std::io::Cursor;
use std::path::{Path, PathBuf};

const PROMPT: &str = r#"
1). When is the document dated (if any)?
2). What is the document? Eg, invoice, receipt, etc.
4). What should the document title be (if any)?
5). What would be a good filename for this document, use the format {YYYYMMDD}-{title}-{category}.

Output your response as JSON, eg:
{
    "date": "2020-12-24",  // Use the format YYYY-MM-DD
    "category": "invoice"  // Keep the category in lowercase
    "filename": "20201224-dan-murphys-invoice"  // All lowercase, no spaces. Words separated by hyphens.
}
"#;

#[derive(Debug, PartialEq, serde::Deserialize)]
struct DocumentIntelligence {
    date: Option<String>,
    category: Option<String>,
    filename: Option<String>,
}

#[derive(Parser, Debug)]
#[command(version, about)]
struct Args {
    #[arg(short, long, default_value = "")]
    glob_pattern: String,
    #[arg(short, long, default_value = "gpt-4o-mini")]
    model: String,
    #[arg(short, long, default_value = "3")]
    n_pages: usize,
    #[arg(short, long, action)]
    dry_run: bool,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    dotenv().ok();
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
            debug!("Skipping {}", current_filename);
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
            get_document_intelligence(&pdf_path, args.model.as_str(), args.n_pages).await?;

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
    n_pages: usize,
) -> Result<DocumentIntelligence, Box<dyn Error>> {
    let pdf = PDF::from_file(pdf_path)?;

    let render_options = RenderOptionsBuilder::default()
        .greyscale(true)
        .resolution(DPI::Uniform(100))
        .build()?;

    // Ensure n_pages, if usize, doesn't exceed u32 bounds if that's an internal requirement.
    let effective_n_pages = std::cmp::min(n_pages, u32::MAX as usize) as u32;
    let pages_to_render = pdf2image::Pages::Range(1..=effective_n_pages);
    let pages_vec = pdf.render(pages_to_render, render_options)?;

    if pages_vec.is_empty() {
        return Err(format!("No pages could be rendered from PDF: {}. Check if the PDF is valid or n_pages is too small.", pdf_path).into());
    }

    // Stitch the images together
    let mut total_height: u32 = 0;
    let mut max_width: u32 = 0;
    for page in &pages_vec {
        total_height += page.height();
        max_width = max_width.max(page.width());
    }

    if max_width == 0 || total_height == 0 {
        return Err(format!("Rendered pages for {} result in zero dimension image ({}x{}). PDF might be empty or corrupted.", pdf_path, max_width, total_height).into());
    }

    let mut image = DynamicImage::new_rgb8(max_width, total_height);
    let mut y: u32 = 0;
    for page_image in pages_vec {
        image.copy_from(&page_image, 0_u32, y)?;
        y += page_image.height();
    }

    let mut buffer = Cursor::new(Vec::new());
    image.write_to(&mut buffer, ImageFormat::Png)?;

    let client = Client::new();
    let request = CreateChatCompletionRequestArgs::default()
        .model(model)
        .max_tokens(300_u32)
        .temperature(0.0)
        .messages([ChatCompletionRequestUserMessageArgs::default()
            .content(vec![
                ChatCompletionRequestMessageContentPartTextArgs::default()
                    .text(PROMPT)
                    .build()?
                    .into(),
                ChatCompletionRequestMessageContentPartImageArgs::default()
                    .image_url(
                        ImageUrlArgs::default()
                            .url(format!(
                                "data:image/png;base64,{}",
                                general_purpose::STANDARD.encode(buffer.into_inner())
                            ))
                            .detail(ImageDetail::High)
                            .build()?,
                    )
                    .build()?
                    .into(),
            ])
            .build()?
            .into()])
        .build()?;

    let response = client.chat().create(request).await?;

    let first_choice = response
        .choices
        .first()
        .ok_or("No choices returned from OpenAI API")?;

    let content_str = first_choice
        .message
        .content
        .as_ref()
        .ok_or("No content in OpenAI API response message")?
        .replace("```json\n", "")
        .replace("\n```", "");

    let repaired_json_str = repair_json::repair(content_str.as_str()).map_err(|e_str| {
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
