use std::time::Duration;

/// Basic geometric primitives.
pub mod geometry;
/// Output layouts definitions and utils.
pub mod layout;
/// Relation representation
pub mod relation;

pub trait Backend {
    /// Access the current layout. Layout may be unsupported, see [`layout::Layout::status`].
    fn current_layout(&self) -> layout::Layout;

    /// Wait for a change in backend layout.
    /// Error should represent a *hard unrecoverable* error like X server connection failure.
    /// All other errors should be logged and recovered from if possible.
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
        // if unsupported layout : ignore
        // if layout is the same as last requested : ignore
        // if new output set : apply from DB, or autolayout a new one
        // if same outputs but changes : store to db
        layout = new_layout;
    }
}
