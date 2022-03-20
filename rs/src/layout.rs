use crate::geometry::{Direction, Transform, Vec2d};
use std::collections::HashMap;

#[derive(Debug, Clone)]
struct Mode {
    size: Vec2d,
    frequency: f64, // FIXME
}

/// Bytes 8 to 15 of EDID header, containing manufacturer id + serial number.
/// This should be sufficient for unique identification of a display.
#[derive(Debug, Clone, Copy)]
struct Edid([u8; 8]);

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
        let mut id_bytes :[u8; 8] = Default::default();
        id_bytes.copy_from_slice(&bytes[8..16]);
        Ok(Edid(id_bytes))
    }
}

enum OutputState {
    Disabled,
    Enabled { transform: Transform, mode: Mode },
}

/// Layout information in the "good" case where automation can be used.
/// Requires Edid for all outputs.
/// This struct is designed to be serialized in the database.
struct AutomaticModeLayout {
    outputs: HashMap<Edid, OutputState>,
    /// key: (lhs, rhs) with lhs < rhs
    relations: HashMap<(Edid, Edid), Direction>,
    /// Primary output if used / supported. Not in Wayland apparently.
    /// Used by some window manager to choose where to place tray icons, etc.
    primary: Option<Edid>,
}

// TODO it would be useful to store data for statistical mode, with output names
// Maybe clone of Layout with enum{Edid,OutputName} ?
