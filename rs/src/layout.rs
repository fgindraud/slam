use crate::geometry::{Direction, InvertibleRelation, Rect, Transform, Vec2di};
use std::cmp::Ordering;

///////////////////////////////////////////////////////////////////////////////

/// Bytes 8 to 15 of EDID header, containing manufacturer id + serial number.
/// This should be sufficient for unique identification of a display.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Edid(u64);

impl std::fmt::Debug for Edid {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "Edid({:#016x})", self.0)
    }
}

/// Build from raw full EDID data.
impl<'a> TryFrom<&'a [u8]> for Edid {
    type Error = &'static str;
    fn try_from(bytes: &'a [u8]) -> Result<Edid, &'static str> {
        if !(bytes.len() >= 16) {
            // Very permissive here as we only need the bytes 8-15.
            // EDID standard has at least 128 bytes from 1.0 upwards.
            return Err("Edid: bad length");
        }
        if bytes[0..8] != [0x0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x0] {
            return Err("Edid: missing constant header pattern");
        }
        let id_bytes: [u8; 8] = bytes[8..16].try_into().unwrap();
        Ok(Edid(u64::from_be_bytes(id_bytes)))
    }
}

// For tests only
impl From<u64> for Edid {
    fn from(raw: u64) -> Edid {
        Edid(raw)
    }
}

///////////////////////////////////////////////////////////////////////////////

#[derive(Debug, Clone)]
pub struct Mode {
    pub size: Vec2di,
    pub frequency: f64, // FIXME
}

/// Identifier for an output : , or the output name.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub enum OutputId {
    /// [`Edid`] is prefered if available
    Edid(Edid),
    /// Fallback to output name and monitor preferred size
    Name(String),
}

/// State and identification for an enabled output.
#[derive(Debug)]
pub struct EnabledOutput {
    pub id: OutputId,
    pub mode: Mode,
    pub transform: Transform,
    pub bottom_left: Vec2di,
}

/// State of a set of screen outputs and their relative positionning.
/// Intended to be stored in the database.
/// Lists all connected outputs of a system.
#[derive(Debug)]
pub struct Layout {
    /// Disabled outputs : only list their ids.
    pub disabled_outputs: Box<[OutputId]>,
    /// Enabled output states.
    pub enabled_outputs: Box<[EnabledOutput]>,
    /// Primary output if used / supported. Not in Wayland apparently.
    /// Used by some window manager to choose where to place tray icons, etc.
    /// Index is a reference in `enabled_outputs`.
    pub primary: Option<u16>,
}

// TODO it would be useful to store data for statistical mode, with output names
// TODO serialization

impl EnabledOutput {
    /// Rect occupied by monitor in abstract 2D space (X11 screen)
    fn rect(&self) -> Rect {
        Rect {
            bottom_left: self.bottom_left.clone(),
            size: self.mode.size.clone().apply(&self.transform),
        }
    }
}

impl Layout {
    /// Return the list of outputs ids, sorted.
    pub fn connected_outputs(&self) -> Box<[OutputId]> {
        let mut v = Vec::from_iter(Iterator::chain(
            self.disabled_outputs.iter().cloned(),
            self.enabled_outputs.iter().map(|o| o.id.clone()),
        ));
        v.sort_unstable();
        Vec::into_boxed_slice(v)
    }
}
