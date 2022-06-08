/// Basic geometric primitives.
pub mod geometry;
/// Output layouts definitions and utils.
pub mod layout;

pub trait Backend {
    fn wait_for_change(&mut self) -> Result<(), anyhow::Error>;
}

/// X backend
#[cfg(feature = "xcb")]
pub mod xcb;