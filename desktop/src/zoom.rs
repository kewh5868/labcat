//! Page zoom stays native: web content gains no Tauri permissions.
use std::sync::Mutex;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::{AppHandle, Manager, Runtime, Window, WindowEvent};

#[path = "zoom_steps.rs"]
mod steps;
use steps::{action, eligible_window, ZoomState, ACTUAL_SIZE, ZOOM_IN, ZOOM_IN_PLUS, ZOOM_OUT};

#[derive(Default)]
struct WindowZoom(Mutex<ZoomState>);

pub fn install<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    // Preserve standard application, Edit, Window, Help and fullscreen actions.
    let menu = Menu::default(app)?;
    let existing_view = menu.items()?.into_iter().find_map(|item| {
        let submenu = item.as_submenu()?;
        (submenu.text().ok().as_deref() == Some("View")).then(|| submenu.clone())
    });
    let view = match existing_view {
        Some(view) => {
            view.append(&PredefinedMenuItem::separator(app)?)?;
            view
        }
        None => {
            let view = Submenu::with_id(app, "labcat-view", "View", true)?;
            menu.append(&view)?;
            view
        }
    };
    let zoom_in = MenuItem::with_id(app, ZOOM_IN, "Zoom In", true, Some("CmdOrCtrl+="))?;
    let zoom_out = MenuItem::with_id(app, ZOOM_OUT, "Zoom Out", true, Some("CmdOrCtrl+-"))?;
    let actual_size =
        MenuItem::with_id(app, ACTUAL_SIZE, "Actual Size", true, Some("CmdOrCtrl+0"))?;
    // '+' is Shift+'=' on many keyboards. Menu accelerators remain available
    // even while a sandboxed structure iframe or an input has keyboard focus.
    let alternate_in = MenuItem::with_id(
        app,
        ZOOM_IN_PLUS,
        "Zoom In (+)",
        true,
        Some("CmdOrCtrl+Shift+="),
    )?;
    let shortcuts = Submenu::with_items(app, "Keyboard Shortcuts", true, &[&alternate_in])?;
    view.append_items(&[&zoom_in, &zoom_out, &actual_size, &shortcuts])?;
    app.manage(WindowZoom::default());
    app.set_menu(menu)?;
    app.on_menu_event(|app, event| {
        let Some(action) = action(event.id().as_ref()) else {
            return;
        };
        // Never apply a shortcut to a background window or external browser.
        let focused = app
            .webview_windows()
            .into_values()
            .find(|window| eligible_window(window.label()) && window.is_focused().unwrap_or(false));
        let Some(window) = focused else {
            return;
        };
        let state = app.state::<WindowZoom>();
        if let Ok(mut state) = state.0.lock() {
            let _ = state.apply(window.label(), action, |scale| window.set_zoom(scale));
        };
    });
    Ok(())
}

pub fn window_event<R: Runtime>(window: &Window<R>, event: &WindowEvent) {
    if matches!(event, WindowEvent::Destroyed) {
        if let Some(state) = window.try_state::<WindowZoom>() {
            if let Ok(mut state) = state.0.lock() {
                state.forget(window.label());
            };
        }
    }
}
