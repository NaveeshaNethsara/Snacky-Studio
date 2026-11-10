#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use std::{net::TcpListener, sync::{Mutex, Arc, atomic::{AtomicBool, Ordering}}, time::Duration};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::{ShellExt, process::CommandChild};
use tauri_plugin_opener::OpenerExt;

struct Backend { port: u16, child: Mutex<Option<CommandChild>>, alive: Arc<AtomicBool> }

fn close_backend(mut child: CommandChild, alive: &AtomicBool) {
    let _ = child.write(b"shutdown\n");
    for _ in 0..150 {
        if !alive.load(Ordering::Acquire) { return; }
        std::thread::sleep(Duration::from_millis(100));
    }
    // One-file Python has a bootloader and a child: stop its whole tree if stuck.
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        let _ = std::process::Command::new("taskkill")
            .args(["/PID", &child.pid().to_string(), "/T", "/F"])
            .creation_flags(0x08000000).output();
    }
    #[cfg(not(windows))]
    let _ = child.kill();
}

#[tauri::command]
fn open_download(path: String, app: tauri::AppHandle, backend: tauri::State<Backend>) -> Result<(), String> {
    // Never let page content turn this command into an arbitrary URL/program opener.
    if !["/api/file/", "/api/browser-download/", "/api/download-file?filename="].iter().any(|prefix| path.starts_with(prefix)) {
        return Err("Choose a completed studio file.".into());
    }
    let url = format!("http://127.0.0.1:{}{}", backend.port, path);
    app.opener().open_url(url, None::<&str>).map_err(|error| error.to_string())
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![open_download])
        .setup(|app| {
            let listener = TcpListener::bind("127.0.0.1:0")?;
            let port = listener.local_addr()?.port(); drop(listener);
            let home = app.path().app_data_dir()?;
            std::fs::create_dir_all(&home)?;
            let (mut events, child) = app.shell().sidecar("snacky-server")?
                .args(["--port".to_string(), port.to_string(), "--home".to_string(), home.to_string_lossy().into_owned(), "--managed".to_string()]).spawn()?;
            let alive = Arc::new(AtomicBool::new(true));
            app.manage(Backend { port, child: Mutex::new(Some(child)), alive: alive.clone() });
            tauri::async_runtime::spawn(async move {
                while let Some(event) = events.recv().await {
                    if matches!(event, tauri_plugin_shell::process::CommandEvent::Terminated(_)) {
                        alive.store(false, Ordering::Release);
                    }
                }
                alive.store(false, Ordering::Release);
            });
            // A startup failure is visible instead of leaving a blank application.
            let mut ready = false;
            for _ in 0..900 {
                if std::net::TcpStream::connect(("127.0.0.1",port)).is_ok() { ready = true; break; }
                std::thread::sleep(Duration::from_millis(100));
            }
            if !ready { return Err("The media backend could not start. Check the desktop build prerequisites.".into()); }
            let url = url::Url::parse(&format!("http://127.0.0.1:{port}/"))?;
            WebviewWindowBuilder::new(app,"main",WebviewUrl::External(url))
                .title("Snacky Studio").inner_size(1120.0,850.0).min_inner_size(390.0,650.0).build()?;
            Ok(())
        })
        .build(tauri::generate_context!()).expect("Could not start Snacky Studio");
    app.run(|app,event| {
        if matches!(event,tauri::RunEvent::Exit) {
            if let Some(state) = app.try_state::<Backend>() {
                if let Some(child) = state.child.lock().unwrap().take() { close_backend(child, &state.alive); }
            }
        }
    });
}
