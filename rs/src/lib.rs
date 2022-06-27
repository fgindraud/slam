use std::time::Duration;

/// Basic geometric primitives.
pub mod geometry;
/// Output layouts definitions and utils.
pub mod layout;

pub trait Backend {
    /// Access the current layout
    fn current_layout(&self) -> layout::Layout;

    /// Wait for a change in backend layout
    fn wait_for_change(&mut self, reaction_delay: Option<Duration>) -> Result<(), anyhow::Error>;
}

/// X backend
#[cfg(feature = "xcb")]
pub mod xcb;

pub fn run_daemon(
    backend: &mut dyn Backend,
    reaction_delay: Option<Duration>,
) -> Result<(), anyhow::Error> {
    let mut layout = backend.current_layout();
    loop {
        dbg!(&layout);
        backend.wait_for_change(reaction_delay)?;
        let new_layout = backend.current_layout();
        // TODO
        // if weird layout : ignore FIXME must be done before creating a Layout struct
        // if layout is the same as last requested : ignore
        // if new output set : apply from DB, or autolayout a new one
        // if same outputs but changes : store to db
        layout = new_layout;
    }
}
