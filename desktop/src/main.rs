#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod zoom;

use std::io::{Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use tauri::webview::{DownloadEvent, NewWindowResponse, PageLoadEvent};
use tauri::{AppHandle, Manager, Url, WebviewUrl, WebviewWindowBuilder};

const TITLE: &str = "Labcat";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(90);
const MAX_OUTPUT: usize = 24 * 1024;

/// Require the literal loopback address, a numeric explicit port, and root path.
fn validate_url(raw: &str) -> Result<Url, String> {
    let remainder = raw
        .strip_prefix("http://127.0.0.1:")
        .ok_or("Use --url http://127.0.0.1:PORT/ with a local application port.")?;
    let port = remainder.strip_suffix('/').unwrap_or(remainder);
    if port.is_empty() || port.len() > 5 || !port.bytes().all(|c| c.is_ascii_digit()) {
        return Err("The application URL must contain only a numeric port and root path.".into());
    }
    if port
        .parse::<u16>()
        .ok()
        .filter(|value| *value != 0)
        .is_none()
    {
        return Err("The application port must be between 1 and 65535.".into());
    }
    Url::parse(&format!("http://127.0.0.1:{port}/")).map_err(|e| e.to_string())
}

fn parse_arguments(args: &[String]) -> Result<Option<Url>, String> {
    match args {
        [] => Ok(None),
        [flag, value] if flag == "--url" => validate_url(value).map(Some),
        _ => Err("Usage: Labcat [--url http://127.0.0.1:PORT/]".into()),
    }
}

fn launcher_url(output: &str) -> Result<Url, String> {
    let urls: Vec<_> = output
        .lines()
        .filter_map(|line| {
            line.strip_prefix("Labcat UI: ")
                .or_else(|| line.strip_prefix("Labcat is running at "))
        })
        .collect();
    if urls.len() != 1 {
        return Err("The launcher did not return one unambiguous local application URL.".into());
    }
    validate_url(urls[0].trim())
}

fn same_origin(url: &Url, expected: &Url) -> bool {
    url.scheme() == "http"
        && url.host_str() == Some("127.0.0.1")
        && url.port_or_known_default() == expected.port_or_known_default()
        && url.username().is_empty()
        && url.password().is_none()
}

fn discovery_reference_path(url: &Url) -> bool {
    if url.query().is_some() || url.fragment().is_some() {
        return false;
    }
    match url.host_str() {
        Some("openalex.org") => {
            url.path() == "/"
                || url.path().strip_prefix("/W").is_some_and(|id| {
                    !id.is_empty() && id.len() <= 15 && id.bytes().all(|c| c.is_ascii_digit())
                })
        }
        Some("en.wikipedia.org") => {
            url.path() == "/"
                || url.path().strip_prefix("/wiki/").is_some_and(|title| {
                    let lower = title.to_ascii_lowercase();
                    !title.is_empty()
                        && title.len() <= 1800
                        && !title.contains([':', '/', '\\'])
                        && !["%3a", "%2f", "%5c", "%25", "%0", "%1", "%7f"]
                            .iter()
                            .any(|encoded| lower.contains(encoded))
                })
        }
        Some("www.mediawiki.org") => url.path() == "/wiki/API:Search",
        Some("help.openalex.org") => url.path() == "/api/",
        Some("chemrxiv.org") => url.path() == "/",
        _ => false,
    }
}

fn public_reference(url: &Url) -> bool {
    url.scheme() == "https"
        && url.username().is_empty()
        && url.password().is_none()
        && url.port_or_known_default() == Some(443)
        && (matches!(
            url.host_str(),
            Some(
                "doi.org"
                    | "www.nature.com"
                    | "nature.com"
                    | "materialsproject.org"
                    | "next-gen.materialsproject.org"
                    | "docs.materialsproject.org"
                    | "materialsproject.github.io"
                    | "figshare.com"
                    | "api.figshare.com"
                    | "github.com"
                    | "materials.hybrid3.duke.edu"
                    | "hybrid3-database.readthedocs.io"
                    | "nomad-lab.eu"
                    | "docs.nomad-lab.eu"
                    | "europepmc.org"
                    | "arxiv.org"
                    | "info.arxiv.org"
                    | "docs.aws.amazon.com"
            )
        ) || discovery_reference_path(url)
            || (url.host_str() == Some("learn.chatgpt.com")
                && url.path() == "/docs/auth"
                && url.query().is_none()
                && matches!(url.fragment(), None | Some("login-on-headless-devices")))
            || (url.query().is_none()
                && url.fragment().is_none()
                && matches!(
                    (url.host_str(), url.path()),
                    (
                        Some("www.nobelprize.org"),
                        "/prizes/physics/2010/press-release/"
                            | "/prizes/chemistry/2011/press-release/"
                            | "/prizes/chemistry/2000/press-release/"
                    ) | (Some("science.nasa.gov"), "/mission/stardust/")
                        | (Some("goose-docs.ai"), "/")
                )))
}

fn report_download(url: &Url, expected: &Url) -> bool {
    let parts: Vec<_> = url.path().split('/').collect();
    same_origin(url, expected)
        && parts.len() == 7
        && parts[1] == "api"
        && parts[2] == "chats"
        && parts[4] == "reports"
        && parts[6] == "export"
        && [parts[3], parts[5]].iter().all(|id| {
            !id.is_empty()
                && id.len() <= 64
                && id.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-')
        })
}

fn preview_download(url: &Url, expected: &Url) -> bool {
    let parts: Vec<_> = url.path().split('/').collect();
    same_origin(url, expected)
        && parts.len() == 5
        && parts[1] == "api"
        && parts[2] == "report-preview"
        && parts[3] == "download"
        && parts[4].len() == 32
        && parts[4]
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}

fn structure_download(url: &Url, expected: &Url) -> bool {
    let parts: Vec<_> = url.path().split('/').collect();
    if !same_origin(url, expected)
        || url.query().is_some()
        || url.fragment().is_some()
        || parts.len() != 9
        || parts[1] != "api"
        || parts[2] != "chats"
        || parts[4] != "reports"
        || parts[6] != "structures"
        || parts[8] != "download"
        || ![parts[3], parts[5]].iter().all(|id| {
            !id.is_empty()
                && id.len() <= 64
                && id.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-')
        })
    {
        return false;
    }
    if let Some(id) = parts[7].strip_prefix("mp-") {
        return !id.is_empty() && id.len() <= 10 && id.bytes().all(|c| c.is_ascii_digit());
    }
    for prefix in ["dielectric%3Amp-", "dielectric%3amp-", "dielectric:mp-"] {
        if let Some(tail) = parts[7].strip_prefix(prefix) {
            let normalized = tail.replace("%3A", ":").replace("%3a", ":");
            let mut segments = normalized.split(":row");
            let id = segments.next().unwrap_or("");
            let row = segments.next();
            return !id.is_empty()
                && id.len() <= 10
                && id.bytes().all(|c| c.is_ascii_digit())
                && row.is_none_or(|index| {
                    !index.is_empty()
                        && index.len() <= 4
                        && index.bytes().all(|c| c.is_ascii_digit())
                })
                && segments.next().is_none();
        }
    }
    ["nomad%3A", "nomad%3a", "nomad:"].iter().any(|prefix| {
        parts[7].strip_prefix(prefix).is_some_and(|id| {
            !id.is_empty()
                && id.len() <= 80
                && id
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'_' | b'-'))
        })
    })
}

/// Ignore remote filenames and choose a fresh file only in the OS Downloads folder.
fn download_destination(url: &Url, expected: &Url, downloads: &Path) -> Option<PathBuf> {
    let structure = structure_download(url, expected);
    if !(report_download(url, expected) || preview_download(url, expected) || structure)
        || !downloads.is_dir()
    {
        return None;
    }
    let presentation: Vec<_> = url
        .query_pairs()
        .filter(|(key, _)| key == "format_source")
        .map(|(_, value)| value.into_owned())
        .collect();
    if !presentation.is_empty()
        && (!report_download(url, expected)
            || !matches!(presentation.as_slice(), [value] if value == "saved" || value == "current"))
    {
        return None;
    }
    let formats: Vec<_> = url
        .query_pairs()
        .filter(|(key, _)| key == "format")
        .map(|(_, value)| value.into_owned())
        .collect();
    let extension = if structure {
        "cif"
    } else {
        match formats.as_slice() {
            [value] if value == "text" => "txt",
            [value] if matches!(value.as_str(), "txt" | "json" | "pdf" | "docx") => value.as_str(),
            _ => return None,
        }
    };
    let report_id = if preview_download(url, expected) {
        "preview"
    } else {
        url.path().split('/').nth(5)?
    };
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()?
        .as_nanos();
    for sequence in 0..100 {
        let name = format!("labcat-{report_id}-{nonce}-{sequence}.{extension}");
        let destination = downloads.join(name);
        match std::fs::symlink_metadata(&destination) {
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Some(destination),
            Ok(_) => continue,
            Err(_) => return None,
        }
    }
    None
}

fn allow_download(app: &AppHandle, url: &Url, expected: &Url, target: &mut PathBuf) -> bool {
    let Some(destination) = app
        .path()
        .download_dir()
        .ok()
        .and_then(|directory| download_destination(url, expected, &directory))
    else {
        return false;
    };
    *target = destination;
    true
}

// Provider-owned authentication is a navigation capability, never evidence.
fn provider_sign_in(url: &Url) -> bool {
    url.scheme() == "https"
        && url.host_str() == Some("auth.openai.com")
        && url.port_or_known_default() == Some(443)
        && url.username().is_empty()
        && url.password().is_none()
        && url.fragment().is_none()
        && ((url.path() == "/codex/device" && url.query().is_none()) || goose_browser_sign_in(url))
}

fn goose_browser_sign_in(url: &Url) -> bool {
    // Native Goose 1.50.0's reviewed PKCE client and loopback callback. Optional
    // upstream parameters are accepted only once; all required values are fixed.
    if url.as_str().len() > 8192
        || !url
            .as_str()
            .starts_with("https://auth.openai.com/oauth/authorize?")
        || !url.as_str().bytes().all(|byte| (33..127).contains(&byte))
    {
        return false;
    }
    let Some(raw_query) = url.query() else {
        return false;
    };
    if raw_query.split('&').any(|field| !field.contains('=')) {
        return false;
    }
    let mut query = std::collections::BTreeMap::new();
    for (name, value) in url.query_pairs() {
        if query.insert(name, value).is_some() {
            return false;
        }
    }
    for (name, expected) in [
        ("client_id", "app_EMoamEEZ73f0CkXaXp7hrann"),
        ("redirect_uri", "http://localhost:1455/auth/callback"),
        ("response_type", "code"),
        ("code_challenge_method", "S256"),
    ] {
        if query.get(name).map(|value| value.as_ref()) != Some(expected) {
            return false;
        }
    }
    ["state", "code_challenge"].iter().all(|name| {
        query.get(*name).is_some_and(|value| {
            (20..=256).contains(&value.len())
                && value
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
        })
    })
}

/// Open approved public references in the system browser, outside the app webview.
fn open_reference(url: &Url) {
    if !public_reference(url) && !provider_sign_in(url) {
        return;
    }
    #[cfg(target_os = "macos")]
    let mut command = Command::new("/usr/bin/open");
    #[cfg(target_os = "linux")]
    let mut command = Command::new("xdg-open");
    #[cfg(windows)]
    let mut command = {
        let mut command = Command::new("rundll32.exe");
        command.arg("url.dll,FileProtocolHandler");
        command
    };
    let _ = command
        .arg(url.as_str())
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();
}

/// WebKit can send a new-window link through navigation policy first. Open its
/// approved destination externally before cancelling; never load it in the app.
fn route_navigation<F: FnOnce(&Url)>(url: &Url, expected: &Url, open: F) -> bool {
    if same_origin(url, expected) {
        return true;
    }
    if public_reference(url) || provider_sign_in(url) {
        open(url);
    }
    false
}

fn capture<R: Read + Send + 'static>(mut stream: R) -> thread::JoinHandle<String> {
    thread::spawn(move || {
        let mut bytes = Vec::new();
        let mut chunk = [0u8; 4096];
        while let Ok(count) = stream.read(&mut chunk) {
            if count == 0 {
                break;
            }
            let remaining = MAX_OUTPUT.saturating_sub(bytes.len());
            bytes.extend_from_slice(&chunk[..count.min(remaining)]);
        }
        String::from_utf8_lossy(&bytes).into_owned()
    })
}

fn launcher_directory(resource_dir: Option<&Path>, executable: &Path) -> Result<PathBuf, String> {
    let bundled = resource_dir.map(|directory| directory.join("launcher"));
    let portable = executable
        .parent()
        .map(|directory| directory.join("launcher"));
    for directory in bundled.into_iter().chain(portable) {
        let launcher = if cfg!(windows) {
            "labcat.ps1"
        } else {
            "labcat.sh"
        };
        if directory.join("compose.yaml").is_file() && directory.join(launcher).is_file() {
            return Ok(directory);
        }
    }
    Err("Bundled launcher resources are missing. Reinstall the complete native application with its launcher folder.".into())
}

fn start_backend(resource_dir: Option<&Path>, deadline: Instant) -> Result<Url, String> {
    let executable = std::env::current_exe()
        .map_err(|e| format!("Cannot locate the native application: {e}"))?;
    let directory = launcher_directory(resource_dir, &executable)?;
    #[cfg(windows)]
    let mut command = {
        use std::os::windows::process::CommandExt;
        let mut command = Command::new("powershell.exe");
        command
            .args(["-NoProfile", "-NonInteractive", "-File"])
            .arg(directory.join("labcat.ps1"))
            .args(["start", "-NoOpen"])
            .creation_flags(0x08000000);
        command
    };
    #[cfg(not(windows))]
    let mut command = {
        let mut command = Command::new("/bin/sh");
        command
            .arg(directory.join("labcat.sh"))
            .args(["start", "--no-open"]);
        command
    };
    let mut child = command
        .current_dir(&directory)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("The bundled launcher could not start: {e}"))?;
    let stdout = capture(
        child
            .stdout
            .take()
            .ok_or("Launcher output was unavailable.")?,
    );
    let stderr = capture(
        child
            .stderr
            .take()
            .ok_or("Launcher diagnostics were unavailable.")?,
    );
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(100)),
            Ok(None) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err("Startup exceeded 90 seconds. Check Docker and the host launcher logs, then reopen the application.".into());
            }
            Err(error) => return Err(format!("Could not read launcher status: {error}")),
        }
    };
    while (!stdout.is_finished() || !stderr.is_finished()) && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(20));
    }
    if !stdout.is_finished() || !stderr.is_finished() {
        return Err("The launcher output did not finish before the startup timeout.".into());
    }
    let output = stdout
        .join()
        .map_err(|_| "Unable to collect launcher output.")?;
    let errors = stderr
        .join()
        .map_err(|_| "Unable to collect launcher diagnostics.")?;
    if !status.success() {
        return Err(format!(
            "Docker startup failed.\n{}\n{}",
            output.trim(),
            errors.trim()
        ));
    }
    launcher_url(&output)
}

fn remaining_time(deadline: Instant) -> Result<Duration, String> {
    let remaining = deadline.saturating_duration_since(Instant::now());
    if remaining.is_zero() {
        Err("The local application startup check timed out.".into())
    } else {
        Ok(remaining.min(Duration::from_secs(3)))
    }
}

fn get_local_json(
    url: &Url,
    path: &str,
    startup_deadline: Instant,
) -> Result<serde_json::Value, String> {
    let deadline = startup_deadline.min(Instant::now() + Duration::from_secs(3));
    let port = url
        .port_or_known_default()
        .ok_or("Missing application port.")?;
    let address = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    let mut stream = TcpStream::connect_timeout(&address, remaining_time(deadline)?)
        .map_err(|_| "The local application is not reachable. Start it and reopen this window.")?;
    stream
        .set_read_timeout(Some(remaining_time(deadline)?))
        .map_err(|e| e.to_string())?;
    stream
        .set_write_timeout(Some(remaining_time(deadline)?))
        .map_err(|e| e.to_string())?;
    write!(stream, "GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAccept: application/json\r\nConnection: close\r\n\r\n")
        .map_err(|e| format!("Local application check failed: {e}"))?;
    let mut response = Vec::new();
    let mut chunk = [0u8; 4096];
    loop {
        stream
            .set_read_timeout(Some(remaining_time(deadline)?))
            .map_err(|e| e.to_string())?;
        let count = stream
            .read(&mut chunk)
            .map_err(|e| format!("Local application response failed: {e}"))?;
        if count == 0 {
            break;
        }
        response.extend_from_slice(&chunk[..count]);
        if response.len() > 65536 {
            return Err("The local status response was too large.".into());
        }
    }
    let text = String::from_utf8(response).map_err(|_| "Invalid local status encoding.")?;
    let (headers, body) = text
        .split_once("\r\n\r\n")
        .ok_or("Invalid local HTTP response.")?;
    if headers
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        != Some("200")
    {
        return Err(
            "The local application is not ready. Its health or status check failed.".into(),
        );
    }
    serde_json::from_str(body)
        .map_err(|_| "The local service did not return application status JSON.".into())
}

fn verify_backend(url: &Url, deadline: Instant) -> Result<(), String> {
    if get_local_json(url, "/health", deadline)?["status"] != "ok" {
        return Err("The local service did not report healthy application status.".into());
    }
    if get_local_json(url, "/api/status?style=pi", deadline)?["application"] != TITLE {
        return Err("The selected port is not serving the Labcat workspace.".into());
    }
    Ok(())
}

fn display_error(app: &AppHandle, error: &str) {
    if let Some(window) = app.get_webview_window("startup") {
        let encoded = serde_json::to_string(error).unwrap_or_else(|_| "\"Startup failed.\"".into());
        let script = format!(
            "document.getElementById('title').textContent='Your workspace could not open.';\
            document.getElementById('message').textContent='The native window is ready, but the local application needs attention.';\
            document.getElementById('details').textContent={encoded};\
            document.getElementById('details').hidden=false;\
            document.getElementById('recovery').hidden=false;"
        );
        let _ = window.eval(&script);
        let _ = window.show();
    }
}

fn open_main(app: &AppHandle, url: Url) -> Result<Arc<AtomicBool>, String> {
    let allowed = url.clone();
    let popup_allowed = url.clone();
    let loaded_origin = url.clone();
    let download_origin = url.clone();
    let popup_app = app.clone();
    let loaded = Arc::new(AtomicBool::new(false));
    let page_loaded = loaded.clone();
    WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
        .title(TITLE)
        .inner_size(1100.0, 800.0)
        .min_inner_size(680.0, 500.0)
        .visible(false)
        .devtools(false)
        .zoom_hotkeys_enabled(false)
        .disable_drag_drop_handler()
        .on_download(move |window, event| match event {
            DownloadEvent::Requested { url, destination } => {
                allow_download(window.app_handle(), &url, &download_origin, destination)
            }
            _ => true,
        })
        .on_navigation(move |destination| route_navigation(destination, &allowed, open_reference))
        .on_document_title_changed(|window, _| {
            let _ = window.set_title(TITLE);
        })
        .on_new_window(move |destination, _| {
            if public_reference(&destination) || provider_sign_in(&destination) {
                open_reference(&destination);
            } else if same_origin(&destination, &popup_allowed) {
                let app = popup_app.clone();
                let allowed = popup_allowed.clone();
                let downloads = popup_allowed.clone();
                thread::spawn(move || {
                    if let Some(existing) = app.get_webview_window("status-export") {
                        let _ = existing.navigate(destination);
                        let _ = existing.show();
                        let _ = existing.set_focus();
                    } else {
                        let _ = WebviewWindowBuilder::new(
                            &app,
                            "status-export",
                            WebviewUrl::External(destination),
                        )
                        .title(TITLE)
                        .inner_size(900.0, 700.0)
                        .devtools(false)
                        .zoom_hotkeys_enabled(false)
                        .on_download(move |window, event| match event {
                            DownloadEvent::Requested { url, destination } => {
                                allow_download(window.app_handle(), &url, &downloads, destination)
                            }
                            _ => true,
                        })
                        .on_navigation(move |next| route_navigation(next, &allowed, open_reference))
                        .on_new_window(|_, _| NewWindowResponse::Deny)
                        .build();
                    }
                });
            }
            NewWindowResponse::Deny
        })
        .on_page_load(move |window, payload| {
            if payload.event() == PageLoadEvent::Finished
                && same_origin(payload.url(), &loaded_origin)
            {
                page_loaded.store(true, Ordering::SeqCst);
                let _ = window.show();
                let _ = window.set_focus();
                if let Some(startup) = window.app_handle().get_webview_window("startup") {
                    let _ = startup.close();
                }
            }
        })
        .build()
        .map_err(|e| format!("The native webview could not be created: {e}"))?;
    Ok(loaded)
}

fn main() {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let supplied_url = parse_arguments(&arguments);
    let error_state: Arc<Mutex<Option<String>>> = Arc::new(Mutex::new(None));
    tauri::Builder::default()
        .on_window_event(zoom::window_event)
        .setup(move |app| {
            zoom::install(app.handle())?;
            let page_error = error_state.clone();
            WebviewWindowBuilder::new(app, "startup", WebviewUrl::App("index.html".into()))
                .title(TITLE).inner_size(1100.0, 800.0).min_inner_size(680.0, 500.0)
                .devtools(false).zoom_hotkeys_enabled(false).disable_drag_drop_handler()
                .on_navigation(|url| {
                    (url.scheme() == "tauri" && url.host_str() == Some("localhost"))
                        || (url.scheme() == "http" && url.host_str() == Some("tauri.localhost"))
                })
                .on_new_window(|_, _| NewWindowResponse::Deny)
                .on_page_load(move |window, payload| {
                    if payload.event() == PageLoadEvent::Finished {
                        if let Ok(error) = page_error.lock() {
                            if let Some(message) = error.as_ref() {
                                display_error(window.app_handle(), message);
                            }
                        }
                    }
                }).build()?;
            let handle = app.handle().clone();
            let resources = app.path().resource_dir().ok();
            thread::spawn(move || {
                let startup_deadline = Instant::now() + STARTUP_TIMEOUT;
                let result = supplied_url.and_then(|url| match url {
                    Some(url) => Ok(url),
                        None => start_backend(resources.as_deref(), startup_deadline),
                }).and_then(|url| {
                        verify_backend(&url, startup_deadline)?;
                    open_main(&handle, url)
                });
                let failure = match result {
                    Err(error) => Some(error),
                    Ok(loaded) => {
                        let deadline = startup_deadline.min(Instant::now() + Duration::from_secs(15));
                        while !loaded.load(Ordering::SeqCst) && Instant::now() < deadline {
                            thread::sleep(Duration::from_millis(100));
                        }
                        if loaded.load(Ordering::SeqCst) { None } else {
                            if let Some(window) = handle.get_webview_window("main") { let _ = window.close(); }
                            Some("The local UI did not finish loading. Check Docker and reopen the application.".into())
                        }
                    }
                };
                if let Some(message) = failure {
                    if let Ok(mut stored) = error_state.lock() { *stored = Some(message.clone()); }
                    display_error(&handle, &message);
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("The operating system could not initialize the native webview.");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn device_login_is_an_exact_navigation_exception_not_evidence() {
        let login = Url::parse("https://auth.openai.com/codex/device").unwrap();
        assert!(provider_sign_in(&login));
        assert!(!public_reference(&login));
        for raw in [
            "http://auth.openai.com/codex/device",
            "https://auth.openai.com.evil.example/codex/device",
            "https://auth.openai.com/codex/device?redirect=https://evil.example",
            "https://auth.openai.com/codex/device#token",
            "https://user@auth.openai.com/codex/device",
            "https://auth.openai.com:444/codex/device",
            "https://auth.openai.com/other",
        ] {
            assert!(!provider_sign_in(&Url::parse(raw).unwrap()), "{raw}");
        }
    }

    #[test]
    fn native_goose_browser_login_requires_the_exact_pkce_client_and_callback() {
        let expected = [
            ("client_id", "app_EMoamEEZ73f0CkXaXp7hrann"),
            ("redirect_uri", "http://localhost:1455/auth/callback"),
            ("response_type", "code"),
            ("code_challenge_method", "S256"),
            ("state", "SYNTHETIC_state_1234567890"),
            ("code_challenge", "SYNTHETIC_challenge_1234567890"),
            ("scope", "openid profile email offline_access"),
            ("originator", "goose"),
        ];
        let mut login = Url::parse("https://auth.openai.com/oauth/authorize").unwrap();
        login.query_pairs_mut().extend_pairs(expected);
        assert!(provider_sign_in(&login));
        assert!(
            !public_reference(&login),
            "Sign-in cannot become source evidence"
        );
        let local = validate_url("http://127.0.0.1:8123/").unwrap();
        let opened = std::cell::Cell::new(false);
        assert!(!route_navigation(&login, &local, |_| opened.set(true)));
        assert!(
            opened.get(),
            "The reviewed sign-in opens in the system browser"
        );
        for (name, value) in [
            ("client_id", "different-client"),
            ("redirect_uri", "http://127.0.0.1:1455/auth/callback"),
            ("redirect_uri", "https://outside.example/callback"),
            ("response_type", "token"),
            ("code_challenge_method", "plain"),
            ("state", "short"),
            ("state", "bad state with spaces"),
            ("code_challenge", ""),
        ] {
            let mut changed = login.clone();
            changed.set_query(None);
            changed
                .query_pairs_mut()
                .extend_pairs(expected.iter().copied().filter(|(key, _)| *key != name))
                .append_pair(name, value);
            assert!(!provider_sign_in(&changed), "{name} override accepted");
        }
        for (name, value) in expected {
            let mut duplicate = login.clone();
            duplicate.query_pairs_mut().append_pair(name, value);
            assert!(!provider_sign_in(&duplicate), "Duplicate {name} accepted");
            if !matches!(name, "scope" | "originator") {
                let mut absent = login.clone();
                absent.set_query(None);
                absent
                    .query_pairs_mut()
                    .extend_pairs(expected.iter().copied().filter(|(key, _)| *key != name));
                assert!(!provider_sign_in(&absent), "Missing {name} accepted");
            }
        }
        for name in ["state", "code_challenge"] {
            for length in [20, 256, 257] {
                let mut sized = login.clone();
                sized.set_query(None);
                sized
                    .query_pairs_mut()
                    .extend_pairs(expected.iter().copied().filter(|(key, _)| *key != name))
                    .append_pair(name, &"a".repeat(length));
                assert_eq!(provider_sign_in(&sized), length <= 256);
            }
        }
        let raw = login.as_str();
        for invalid in [
            raw.replace("https://", "http://"),
            raw.replace("auth.openai.com", "auth.openai.com.evil.example"),
            raw.replace("auth.openai.com", "auth.openai.com:444"),
            raw.replace("auth.openai.com", "user@auth.openai.com"),
            raw.replace("/oauth/authorize?", "/oauth/authorize/other?"),
            format!("{raw}#"),
            format!("{raw}#fragment"),
            format!("{raw}&%73tate=SYNTHETIC_duplicate_state"),
            format!("{raw}&missing_equals"),
            format!("{raw}&"),
            format!("{raw}&extra={}", "a".repeat(8192)),
        ] {
            let changed = Url::parse(&invalid).unwrap();
            assert!(!provider_sign_in(&changed));
            assert!(!route_navigation(&changed, &local, |_| panic!(
                "Unreviewed provider sign-in opened"
            )));
        }
    }

    #[test]
    fn downloads_are_only_persisted_local_report_exports() {
        let expected = validate_url("http://127.0.0.1:8123/").unwrap();
        assert!(report_download(
            &expected
                .join("api/chats/abc/reports/def/export?format=pdf&views=both")
                .unwrap(),
            &expected
        ));
        for path in [
            "api/connections",
            "files/private",
            "api/chats/x/reports/y/export/extra",
        ] {
            assert!(!report_download(&expected.join(path).unwrap(), &expected));
        }
        assert!(!report_download(
            &Url::parse("http://127.0.0.1:9999/api/chats/a/reports/b/export").unwrap(),
            &expected
        ));
    }

    #[test]
    fn preview_downloads_require_same_origin_and_an_exact_ticket() {
        let expected = validate_url("http://127.0.0.1:8123/").unwrap();
        let path = "api/report-preview/download/0123456789abcdef0123456789abcdef?format=text";
        assert!(preview_download(&expected.join(path).unwrap(), &expected));
        for path in [
            "api/report-preview/download/1234?format=pdf",
            "api/report-preview/download/0123456789abcdef0123456789abcdeg?format=pdf",
            "api/report-preview/download/0123456789abcdef0123456789abcdef/extra?format=pdf",
            "api/report-preview/download-link?format=pdf",
        ] {
            assert!(!preview_download(&expected.join(path).unwrap(), &expected));
        }
        let other = Url::parse("http://127.0.0.1:9999/").unwrap();
        assert!(!preview_download(&other.join(path).unwrap(), &expected));
        let folder = std::env::temp_dir();
        let destination =
            download_destination(&expected.join(path).unwrap(), &expected, &folder).unwrap();
        assert_eq!(destination.extension().unwrap(), "txt");
        assert_eq!(destination.parent(), Some(folder.as_path()));
        assert!(destination
            .file_name()
            .unwrap()
            .to_string_lossy()
            .starts_with("labcat-preview-"));
    }

    #[test]
    fn structure_files_use_exact_local_download_paths_and_fixed_cif_extension() {
        let expected = validate_url("http://127.0.0.1:8123/").unwrap();
        let folder = std::env::temp_dir();
        for material in [
            "mp-123",
            "nomad%3Atest_123",
            "dielectric%3Amp-123",
            "dielectric%3Amp-123%3Arow1055",
        ] {
            let url = expected
                .join(&format!(
                    "api/chats/abc/reports/def/structures/{material}/download"
                ))
                .unwrap();
            assert!(structure_download(&url, &expected));
            let destination = download_destination(&url, &expected, &folder).unwrap();
            assert_eq!(destination.extension().unwrap(), "cif");
            assert_eq!(destination.parent(), Some(folder.as_path()));
        }
        for suffix in [
            "mp-123/content",
            "mp-123/download?format=exe",
            "mp-123/download#fragment",
            "mp-123/download/extra",
            "mp-x/download",
            "nomad%253Atest/download",
            "nomad%3A..%2Ffile/download",
            "dielectric%253Amp-123/download",
            "dielectric%3Amp-123%3Arow10000/download",
            "dielectric%3Amp-123%3Arow3%3Arow4/download",
            "dielectric%3Amp-123%2Fetc/download",
            "dielectric%3Amp-x/download",
        ] {
            let url = expected
                .join(&format!("api/chats/abc/reports/def/structures/{suffix}"))
                .unwrap();
            assert!(!structure_download(&url, &expected));
            assert!(download_destination(&url, &expected, &folder).is_none());
        }
        let other = Url::parse(
            "http://127.0.0.1:9999/api/chats/abc/reports/def/structures/mp-123/download",
        )
        .unwrap();
        assert!(!structure_download(&other, &expected));
        for (length, accepted) in [(80, true), (81, false)] {
            let url = expected
                .join(&format!(
                    "api/chats/abc/reports/def/structures/nomad%3A{}/download",
                    "a".repeat(length),
                ))
                .unwrap();
            assert_eq!(structure_download(&url, &expected), accepted);
            assert_eq!(
                download_destination(&url, &expected, &folder).is_some(),
                accepted
            );
        }
        for path in [
            format!(
                "api/chats/{}/reports/def/structures/mp-123/download",
                "a".repeat(65)
            ),
            format!(
                "api/chats/abc/reports/{}/structures/mp-123/download",
                "a".repeat(65)
            ),
        ] {
            assert!(!structure_download(
                &expected.join(&path).unwrap(),
                &expected
            ));
        }
    }

    #[test]
    fn download_paths_ignore_filenames_and_only_add_new_files() {
        let directory = std::env::temp_dir().join(format!(
            "labcat-download-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&directory).unwrap();
        let expected = validate_url("http://127.0.0.1:8123/").unwrap();
        let url = expected
            .join("api/chats/abc/reports/def/export?format=pdf&filename=../../outside")
            .unwrap();
        let first = download_destination(&url, &expected, &directory).unwrap();
        std::fs::write(&first, b"existing report").unwrap();
        let second = download_destination(&url, &expected, &directory).unwrap();
        assert_eq!(first.parent(), Some(directory.as_path()));
        assert_eq!(first.extension().unwrap(), "pdf");
        assert_ne!(first, second);
        assert_eq!(std::fs::read(&first).unwrap(), b"existing report");
        for query in ["format=exe", "format=pdf&format=txt", "format=../../bad"] {
            let bad = expected
                .join(&format!("api/chats/abc/reports/def/export?{query}"))
                .unwrap();
            assert!(download_destination(&bad, &expected, &directory).is_none());
        }
        assert!(download_destination(&url, &expected, &directory.join("missing")).is_none());
        std::fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn public_references_require_approved_https_hosts() {
        assert!(public_reference(
            &Url::parse("https://doi.org/10.6084/m9.figshare.7108790.v2").unwrap()
        ));
        for raw in [
            "https://materials.hybrid3.duke.edu/materials/systems/1/",
            "https://nomad-lab.eu/prod/v1/gui/search/entries/entry/id/example",
            "https://europepmc.org/articles/PMC1234567",
            "https://arxiv.org/abs/2401.00001",
            "https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html",
        ] {
            assert!(public_reference(&Url::parse(raw).unwrap()), "{raw}");
        }
        for raw in [
            "http://doi.org/path",
            "https://doi.org.evil.example/path",
            "https://user@doi.org/path",
            "https://doi.org:8443/path",
            "file:///etc/passwd",
            "https://127.0.0.1/path",
            "https://arxiv.org.evil.example/abs/2401.00001",
            "https://user:password@europepmc.org/articles/PMC1234567",
        ] {
            assert!(!public_reference(&Url::parse(raw).unwrap()), "{raw}");
        }
    }

    #[test]
    fn discovery_links_use_reviewed_public_paths_only() {
        for raw in [
            "https://en.wikipedia.org/wiki/Hydrogel",
            "https://en.wikipedia.org/wiki/High-%CE%BAC_dielectric",
            "https://openalex.org/W1234567890",
            "https://www.mediawiki.org/wiki/API:Search",
            "https://help.openalex.org/api/",
            "https://chemrxiv.org/",
        ] {
            assert!(public_reference(&Url::parse(raw).unwrap()), "{raw}");
        }
        for raw in [
            "http://en.wikipedia.org/wiki/Hydrogel",
            "https://en.wikipedia.org/wiki/Special:UserLogin",
            "https://en.wikipedia.org/wiki/Special%3AUserLogin",
            "https://en.wikipedia.org/wiki/Special%253AUserLogin",
            "https://en.wikipedia.org/wiki/Hydrogel?redirect=elsewhere",
            "https://en.wikipedia.org/wiki/Hydrogel#Other",
            "https://en.wikipedia.org/wiki/A%2fB",
            "https://en.wikipedia.org/wiki/A%0aB",
            "https://en.wikipedia.org.evil.example/wiki/Hydrogel",
            "https://openalex.org/Wabc",
            "https://openalex.org/W1234567890123456",
            "https://openalex.org/W123/other",
            "https://openalex.org/W123?token=anything",
            "https://user@openalex.org/W123",
            "https://chemrxiv.org/private/path",
        ] {
            assert!(!public_reference(&Url::parse(raw).unwrap()), "{raw}");
        }
    }

    #[test]
    fn report_downloads_preserve_explicit_presentation_choice() {
        let expected = validate_url("http://127.0.0.1:8123/").unwrap();
        let folder = std::env::temp_dir();
        for source in ["saved", "current"] {
            let url = expected
                .join(&format!(
                    "api/chats/a/reports/b/export?format=pdf&views=both&format_source={source}"
                ))
                .unwrap();
            assert!(download_destination(&url, &expected, &folder).is_some());
        }
        for choice in ["unknown", "current&format_source=saved", ""] {
            let url = expected
                .join(&format!(
                    "api/chats/a/reports/b/export?format=pdf&format_source={choice}"
                ))
                .unwrap();
            assert!(download_destination(&url, &expected, &folder).is_none());
        }
    }

    #[test]
    fn model_signin_help_opens_only_the_exact_official_guide() {
        let local = validate_url("http://127.0.0.1:8123/").unwrap();
        for raw in [
            "https://learn.chatgpt.com/docs/auth",
            "https://learn.chatgpt.com/docs/auth#login-on-headless-devices",
        ] {
            let url = Url::parse(raw).unwrap();
            assert!(public_reference(&url));
            let opened = std::cell::Cell::new(false);
            assert!(!route_navigation(&url, &local, |_| opened.set(true)));
            assert!(opened.get());
        }
        for raw in [
            "https://learn.chatgpt.com/",
            "https://learn.chatgpt.com/docs/auth/other",
            "https://learn.chatgpt.com/docs/auth?redirect=elsewhere",
            "https://learn.chatgpt.com/docs/auth#other",
            "http://learn.chatgpt.com/docs/auth",
            "https://learn.chatgpt.com:444/docs/auth",
            "https://user@learn.chatgpt.com/docs/auth",
            "https://learn.chatgpt.com.evil.example/docs/auth",
        ] {
            let url = Url::parse(raw).unwrap();
            assert!(!public_reference(&url), "{raw}");
            assert!(!route_navigation(&url, &local, |_| panic!(
                "Unapproved guide opened"
            )));
        }
    }

    #[test]
    fn goose_help_opens_only_the_official_homepage() {
        let local = validate_url("http://127.0.0.1:8123/").unwrap();
        let homepage = Url::parse("https://goose-docs.ai/").unwrap();
        assert!(public_reference(&homepage));
        let opened = std::cell::Cell::new(false);
        assert!(!route_navigation(&homepage, &local, |url| {
            assert_eq!(url, &homepage);
            opened.set(true);
        }));
        assert!(opened.get());

        for raw in [
            "https://goose-docs.ai/docs/",
            "https://goose-docs.ai/?redirect=elsewhere",
            "https://goose-docs.ai/#other",
            "http://goose-docs.ai/",
            "https://goose-docs.ai:444/",
            "https://user@goose-docs.ai/",
            "https://user:password@goose-docs.ai/",
            "https://goose-docs.ai.evil.example/",
            "https://www.goose-docs.ai/",
        ] {
            let url = Url::parse(raw).unwrap();
            assert!(!public_reference(&url), "{raw}");
            assert!(!route_navigation(&url, &local, |_| panic!(
                "Unapproved Goose URL opened"
            )));
        }
    }

    #[test]
    fn materials_facts_open_only_the_reviewed_primary_source_pages() {
        let local = validate_url("http://127.0.0.1:8123/").unwrap();
        for raw in [
            "https://www.nobelprize.org/prizes/physics/2010/press-release/",
            "https://www.nobelprize.org/prizes/chemistry/2011/press-release/",
            "https://www.nobelprize.org/prizes/chemistry/2000/press-release/",
            "https://science.nasa.gov/mission/stardust/",
        ] {
            let url = Url::parse(raw).unwrap();
            assert!(public_reference(&url), "{raw}");
            let opened = std::cell::Cell::new(false);
            assert!(!route_navigation(&url, &local, |_| opened.set(true)));
            assert!(opened.get());
            for suffix in ["other", "?redirect=elsewhere", "#other"] {
                let changed = Url::parse(&format!("{raw}{suffix}")).unwrap();
                assert!(!public_reference(&changed), "{changed}");
            }
        }
        for raw in [
            "https://www.nobelprize.org/",
            "https://www.nobelprize.org/prizes/physics/2011/press-release/",
            "https://www.nobelprize.org/prizes/chemistry/2000/press-release",
            "http://www.nobelprize.org/prizes/physics/2010/press-release/",
            "https://www.nobelprize.org:444/prizes/physics/2010/press-release/",
            "https://user@www.nobelprize.org/prizes/physics/2010/press-release/",
            "https://www.nobelprize.org.evil.example/prizes/physics/2010/press-release/",
            "https://science.nasa.gov/",
            "https://science.nasa.gov/mission/other/",
            "http://science.nasa.gov/mission/stardust/",
            "https://science.nasa.gov:444/mission/stardust/",
            "https://user:password@science.nasa.gov/mission/stardust/",
            "https://science.nasa.gov.evil.example/mission/stardust/",
        ] {
            let url = Url::parse(raw).unwrap();
            assert!(!public_reference(&url), "{raw}");
            assert!(!route_navigation(&url, &local, |_| panic!(
                "Unreviewed fact source opened"
            )));
        }
    }

    #[test]
    fn accepts_explicit_local_root_urls_only() {
        for raw in [
            "http://127.0.0.1:1/",
            "http://127.0.0.1:65535",
            "http://127.0.0.1:80/",
        ] {
            assert!(validate_url(raw).is_ok(), "{raw}");
        }
        for raw in [
            "https://example.org/",
            "http://localhost:8000/",
            "http://127.1:8000/",
            "http://2130706433:8000/",
            "http://127.0.0.1:0/",
            "http://127.0.0.1:65536/",
            "http://127.0.0.1:8000/path",
            "http://127.0.0.1:8000/?x=1",
            "http://127.0.0.1:8000/#x",
            "http://127.0.0.1:8000@evil.example/",
            "file:///etc/passwd",
            "http://[::1]:8000/",
        ] {
            assert!(validate_url(raw).is_err(), "{raw}");
        }
    }

    #[test]
    fn rejects_ambiguous_launcher_output_and_unrecognized_arguments() {
        assert!(launcher_url("Labcat UI: http://127.0.0.1:8123/\n").is_ok());
        assert!(launcher_url("Labcat is running at http://127.0.0.1:8123\n").is_ok());
        assert!(launcher_url("Random URL http://127.0.0.1:8123/\n").is_err());
        assert!(launcher_url(
            "Labcat UI: http://127.0.0.1:8123/\nLabcat UI: http://127.0.0.1:9999/\n"
        )
        .is_err());
        assert!(parse_arguments(&[]).unwrap().is_none());
        assert!(
            parse_arguments(&["--url".into(), "http://127.0.0.1:8123/".into()])
                .unwrap()
                .is_some()
        );
        assert!(parse_arguments(&["--shell".into(), "echo unsafe".into()]).is_err());
    }

    #[test]
    fn navigation_cannot_leave_selected_local_origin() {
        let expected = validate_url("http://127.0.0.1:8123/").unwrap();
        assert!(same_origin(
            &expected.join("api/status?style=audit").unwrap(),
            &expected
        ));
        for raw in [
            "http://127.0.0.1:8124/",
            "https://127.0.0.1:8123/",
            "http://example.org:8123/",
            "http://user@127.0.0.1:8123/",
        ] {
            assert!(!same_origin(&Url::parse(raw).unwrap(), &expected));
        }
    }

    #[test]
    fn approved_navigation_opens_externally_without_loading_in_app() {
        let expected = validate_url("http://127.0.0.1:8123/").unwrap();
        for raw in [
            "https://next-gen.materialsproject.org/api",
            "https://next-gen.materialsproject.org/dashboard",
            "https://hybrid3-database.readthedocs.io/en/latest/website.html",
            "https://docs.nomad-lab.eu/develop/howto/manage/program/api.html",
            "https://europepmc.org/RestfulWebService",
            "https://info.arxiv.org/help/api/user-manual.html",
            "https://auth.openai.com/codex/device",
        ] {
            let destination = Url::parse(raw).unwrap();
            let opened = std::cell::Cell::new(false);
            assert!(!route_navigation(&destination, &expected, |url| {
                assert_eq!(url, &destination);
                opened.set(true);
            }));
            assert!(opened.get(), "{raw}");
        }
    }

    #[test]
    fn local_and_disallowed_navigation_never_launch_external_programs() {
        let expected = validate_url("http://127.0.0.1:8123/").unwrap();
        let unexpected_open = |_: &Url| panic!("This navigation must not launch a browser");
        for path in [
            "",
            "api/status?style=pi",
            "api/report-preview/render/0123456789abcdef",
        ] {
            assert!(route_navigation(
                &expected.join(path).unwrap(),
                &expected,
                unexpected_open,
            ));
        }
        for raw in [
            "http://127.0.0.1:8124/",
            "https://127.0.0.1:8123/",
            "https://next-gen.materialsproject.org.evil.example/api",
            "https://user@next-gen.materialsproject.org/api",
            "https://next-gen.materialsproject.org:444/api",
            "https://auth.openai.com/codex/device?redirect=https://evil.example",
            "https://unapproved.example/",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "data:text/html,unapproved",
        ] {
            assert!(
                !route_navigation(&Url::parse(raw).unwrap(), &expected, unexpected_open,),
                "{raw}"
            );
        }
    }

    #[test]
    fn frontend_has_no_native_api_capability() {
        let config: serde_json::Value =
            serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        assert_eq!(config["app"]["withGlobalTauri"], false);
        for capability in config["app"]["security"]["capabilities"]
            .as_array()
            .unwrap()
        {
            assert_eq!(capability["local"], false);
            assert!(capability["permissions"].as_array().unwrap().is_empty());
            assert!(capability.get("remote").is_none());
        }
    }

    #[test]
    fn launcher_fallback_uses_only_fixed_executable_sibling() {
        let root =
            std::env::temp_dir().join(format!("labcat-native-resources-{}", std::process::id()));
        let primary = root.join("bundle");
        let executable = root.join("portable").join("Labcat.exe");
        let fallback = root.join("portable/launcher");
        std::fs::create_dir_all(&fallback).unwrap();
        for name in ["compose.yaml", "labcat.sh", "labcat.ps1"] {
            std::fs::write(fallback.join(name), "fixture").unwrap();
        }
        assert_eq!(
            launcher_directory(Some(&primary), &executable).unwrap(),
            fallback
        );
        assert_eq!(launcher_directory(None, &executable).unwrap(), fallback);
        let bundled = primary.join("launcher");
        std::fs::create_dir_all(&bundled).unwrap();
        for name in ["compose.yaml", "labcat.sh", "labcat.ps1"] {
            std::fs::write(bundled.join(name), "fixture").unwrap();
        }
        assert_eq!(
            launcher_directory(Some(&primary), &executable).unwrap(),
            bundled
        );
        assert!(launcher_directory(None, &root.join("absent/app")).is_err());
        std::fs::remove_dir_all(root).unwrap();
    }
}
