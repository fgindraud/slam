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

    /// Apply layout to the system using the backend.
    fn apply_layout(&mut self, layout: &layout::Layout) -> Result<(), anyhow::Error>;
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
        if new_layout == layout {
            // if layout is the same as last seen or requested : ignore
            log::debug!("layout unchanged, ignored")
        } else if Iterator::eq(new_layout.connected_outputs(), layout.connected_outputs()) {
            // same outputs but changes : store to db if supported
            if unsupported_causes.is_empty() {
                log::info!("layout changed: storing to database");
                database.store_layout(new_layout.clone())?;
            } else {
                log::warn!("layout changed: ignored because unsupported: {:?}", unsupported_causes);
            }
            layout = new_layout
        } else {
            // new output set
            let by_id = database::LayoutById(new_layout);
            if let Some(stored_layout) = database.get_layout(&by_id) {
                // apply
                log::info!("apply layout from database");
                backend.apply_layout(stored_layout)?;
                layout = stored_layout.clone()
            } else {
                // autolayout
                log::info!("use auto-generated layout (not functionnal)");
                let database::LayoutById(new_layout) = by_id;
                todo!()
            }
        }
    }
}
