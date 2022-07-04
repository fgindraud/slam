use std::time::Duration;

/// Layout database.
pub mod database;
/// Basic geometric primitives.
pub mod geometry;
/// Output layouts definitions and utils.
pub mod layout;
/// Relation representation
pub mod relation;

pub trait Backend {
    /// Access the current layout and support status.
    fn current_layout(&self) -> layout::LayoutInfo;

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
    database: &mut database::Database,
) -> Result<(), anyhow::Error> {
    let layout::LayoutInfo { mut layout, .. } = backend.current_layout();
    loop {
        dbg!(&layout);
        backend.wait_for_change(reaction_delay)?;
        let layout::LayoutInfo {
            layout: new_layout,
            unsupported_causes,
        } = backend.current_layout();
        // Select behavior
        if !unsupported_causes.is_empty() {
            log::warn!("unsupported layout ({:?}), ignored", unsupported_causes)
        } else if new_layout == layout {
            // if layout is the same as last seen or requested : ignore
            log::debug!("layout unchanged, ignored")
        } else if Iterator::eq(new_layout.connected_outputs(), layout.connected_outputs()) {
            // same outputs but changes : store to db
            // TODO
        } else {
            // if new output set : apply from DB, or autolayout a new one
            // TODO
            // store requested layout in `layout` var
        }
        layout = new_layout;
    }
}
