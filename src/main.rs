use async_openai::{
    types::{
        ChatCompletionRequestMessageContentPartImageArgs,
        ChatCompletionRequestMessageContentPartTextArgs, ChatCompletionRequestUserMessageArgs,
        CreateChatCompletionRequestArgs, ImageDetail, ImageUrlArgs,
    },
    Client,
};
use base64;
use clap::Parser;
use colog;
use dotenvy::dotenv;
use glob::glob;
use image::{DynamicImage, GenericImage, ImageFormat};
use log::{debug, info};
use pdf2image::{RenderOptionsBuilder, DPI, PDF};
use regex::Regex;
use repair_json;
use serde_json;
use std::error::Error;
use std::fs;
use std::io::Cursor;
use std::path::Path;

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
    #[arg(short, long, required = true)]
    glob_pattern: String,
    #[arg(short, long, default_value = "gpt-4o-mini")]
    model: String,
    #[arg(short, long, default_value = "3")]
    n_pages: u32,
    #[arg(short, long, action)]
    dry_run: bool,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    dotenv().ok();
    colog::init();
    let args = Args::parse();

    let mut files_to_process: Vec<String> = Vec::new();
    for entry in glob(args.glob_pattern.as_str())? {
        let path = entry?;
        let pdf_path = path.to_str().unwrap();
        let current_filename = Path::new(pdf_path).file_name().unwrap().to_str().unwrap();

        // If it starts with 8 digits and ends with .pdf, skip it
        if Regex::new(r"^\d{8}.*\.pdf$")?.is_match(current_filename) {
            debug!("Skipping {}", current_filename);
            continue;
        }

        files_to_process.push(pdf_path.to_string());
    }

    for pdf_path in files_to_process {
        let current_filename = Path::new(&pdf_path).file_name().unwrap().to_str().unwrap();
        info!("Processing {}", current_filename);

        let document_intelligence =
            get_document_intelligence(&pdf_path, args.model.as_str(), args.n_pages).await?;

        let filename_suggestion = format!("{}.pdf", document_intelligence.filename.unwrap());

        if args.dry_run == true {
            info!(
                "Not renaming {} to {} (dry-run)",
                current_filename, filename_suggestion
            );
        } else {
            let path = Path::new(&pdf_path);
            let new_path = path.with_file_name(&filename_suggestion);
            fs::rename(&pdf_path, new_path)?;

            info!("Renamed {} to {}", current_filename, filename_suggestion);
        }
    }

    Ok(())
}

async fn get_document_intelligence(
    pdf_path: &str,
    model: &str,
    n_pages: u32,
) -> Result<DocumentIntelligence, Box<dyn Error>> {
    let pdf = PDF::from_file(pdf_path)?;
    let pages = pdf.render(
        pdf2image::Pages::Range(1..=n_pages),
        RenderOptionsBuilder::default()
            .greyscale(true)
            .resolution(DPI::Uniform(100))
            .build()
            .unwrap(),
    );

    // Stitch the images together
    let mut total_height = 0;
    let mut max_width = 0;
    for page in pages.as_ref().unwrap() {
        total_height += page.height();
        max_width = max_width.max(page.width());
    }
    let mut image = DynamicImage::new_rgb8(max_width, total_height);
    let mut y = 0;
    for page in pages.unwrap() {
        image.copy_from(&page, 0, y)?;
        y += page.height();
    }

    let mut buffer = Cursor::new(Vec::new());
    image.write_to(&mut buffer, ImageFormat::Png);

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
                                base64::encode(buffer.into_inner())
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
    let content = response.choices[0]
        .message
        .content
        .as_ref()
        .unwrap()
        .replace("```json\n", "")
        .replace("\n```", "");

    let document_intelligence: DocumentIntelligence =
        serde_json::from_str(repair_json::repair(content.clone()).unwrap().as_str())?;

    Ok(document_intelligence)
}
