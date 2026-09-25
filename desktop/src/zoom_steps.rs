//! Small, platform-independent state machine for native page zoom.
use std::collections::HashMap;

pub const ZOOM_IN: &str = "labcat-zoom-in";
pub const ZOOM_IN_PLUS: &str = "labcat-zoom-in-plus";
pub const ZOOM_OUT: &str = "labcat-zoom-out";
pub const ACTUAL_SIZE: &str = "labcat-zoom-actual-size";
const PERCENTAGES: [u16; 10] = [50, 67, 80, 90, 100, 110, 125, 150, 175, 200];
const DEFAULT_INDEX: usize = 4;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action {
    In,
    Out,
    Reset,
}

pub fn action(menu_id: &str) -> Option<Action> {
    match menu_id {
        ZOOM_IN | ZOOM_IN_PLUS => Some(Action::In),
        ZOOM_OUT => Some(Action::Out),
        ACTUAL_SIZE => Some(Action::Reset),
        _ => None,
    }
}

pub fn eligible_window(label: &str) -> bool {
    matches!(label, "main" | "startup" | "status-export")
}

#[derive(Default)]
pub struct ZoomState {
    indices: HashMap<String, usize>,
}

impl ZoomState {
    /// Commit the new level only after the webview accepts it.
    pub fn apply<E>(
        &mut self,
        label: &str,
        action: Action,
        set_zoom: impl FnOnce(f64) -> Result<(), E>,
    ) -> Result<u16, E> {
        let current = self.indices.get(label).copied().unwrap_or(DEFAULT_INDEX);
        let next = match action {
            Action::In => (current + 1).min(PERCENTAGES.len() - 1),
            Action::Out => current.saturating_sub(1),
            Action::Reset => DEFAULT_INDEX,
        };
        let percentage = PERCENTAGES[next];
        set_zoom(f64::from(percentage) / 100.0)?;
        self.indices.insert(label.to_owned(), next);
        Ok(percentage)
    }

    pub fn forget(&mut self, label: &str) {
        self.indices.remove(label);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn change(state: &mut ZoomState, label: &str, action: Action) -> u16 {
        state.apply(label, action, |_| Ok::<(), ()>(())).unwrap()
    }

    #[test]
    fn every_step_and_both_bounds_are_stable() {
        let mut state = ZoomState::default();
        for expected in [110, 125, 150, 175, 200, 200] {
            assert_eq!(change(&mut state, "main", Action::In), expected);
        }
        for expected in [175, 150, 125, 110, 100, 90, 80, 67, 50, 50] {
            assert_eq!(change(&mut state, "main", Action::Out), expected);
        }
    }

    #[test]
    fn reset_returns_to_actual_size_from_each_direction() {
        let mut state = ZoomState::default();
        change(&mut state, "main", Action::In);
        assert_eq!(change(&mut state, "main", Action::Reset), 100);
        change(&mut state, "main", Action::Out);
        assert_eq!(change(&mut state, "main", Action::Reset), 100);
    }

    #[test]
    fn native_failure_does_not_advance_the_saved_step() {
        let mut state = ZoomState::default();
        assert_eq!(
            state.apply("main", Action::In, |_| Err("unavailable")),
            Err("unavailable")
        );
        assert_eq!(change(&mut state, "main", Action::In), 110);
        assert_eq!(
            state.apply("main", Action::Reset, |_| Err("unavailable")),
            Err("unavailable")
        );
        assert_eq!(change(&mut state, "main", Action::In), 125);
    }

    #[test]
    fn each_window_has_an_independent_level_and_reopens_at_actual_size() {
        let mut state = ZoomState::default();
        assert_eq!(change(&mut state, "main", Action::In), 110);
        assert_eq!(change(&mut state, "status-export", Action::Out), 90);
        assert_eq!(change(&mut state, "main", Action::In), 125);
        state.forget("status-export");
        assert_eq!(change(&mut state, "status-export", Action::In), 110);
        assert_eq!(change(&mut state, "main", Action::In), 150);
    }

    #[test]
    fn webview_receives_a_scale_factor_not_a_percentage() {
        let mut state = ZoomState::default();
        state
            .apply("main", Action::In, |value| {
                assert_eq!(value, 1.1);
                Ok::<(), ()>(())
            })
            .unwrap();
    }

    #[test]
    fn only_our_menu_commands_and_local_window_labels_are_recognized() {
        assert_eq!(action(ZOOM_IN), Some(Action::In));
        assert_eq!(action(ZOOM_IN_PLUS), Some(Action::In));
        assert_eq!(action(ZOOM_OUT), Some(Action::Out));
        assert_eq!(action(ACTUAL_SIZE), Some(Action::Reset));
        assert_eq!(action("fullscreen"), None);
        assert!(eligible_window("main"));
        assert!(eligible_window("startup"));
        assert!(eligible_window("status-export"));
        assert!(!eligible_window("provider-sign-in"));
        assert!(!eligible_window("main-other"));
    }
}
