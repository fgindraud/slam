use crate::geometry::{Direction, Transform, Vec2d};
use std::num::NonZeroUsize;

///////////////////////////////////////////////////////////////////////////////

/// Bytes 8 to 15 of EDID header, containing manufacturer id + serial number.
/// This should be sufficient for unique identification of a display.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
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
        let mut id_bytes: [u8; 8] = Default::default();
        id_bytes.copy_from_slice(&bytes[8..16]);
        Ok(Edid(id_bytes))
    }
}

///////////////////////////////////////////////////////////////////////////////

/// Stored representation for an output state.
/// Two modes depending on whether an [`Edid`] is available :
/// - with [`Edid`] as an index : orientation and specific [`Mode`].
/// - fallback using output name, and do not store mode as we cannot differentiate monitors.
#[derive(Debug)]
enum OutputState {
    WithEdid {
        edid: Edid,
        state: OutputWithEdidState,
    },
    WithoutEdid {
        name: String,
        state: OutputWithoutEdidState,
    },
}
#[derive(Debug)]
enum OutputWithEdidState {
    Disabled,
    Enabled { transform: Transform, mode: Mode },
}
#[derive(Debug)]
enum OutputWithoutEdidState {
    Disabled,
    Enabled { transform: Transform },
}

#[derive(Debug, Clone)]
struct Mode {
    size: Vec2d,
    frequency: f64, // FIXME
}

/// Internal identifier for an output.
#[derive(Debug, PartialEq, Eq, PartialOrd, Ord)]
enum OutputId<'s> {
    Edid(Edid),
    Name(&'s str),
}

impl OutputState {
    fn id<'s>(&'s self) -> OutputId<'s> {
        match self {
            OutputState::WithEdid { edid, state: _ } => OutputId::Edid(edid.clone()),
            OutputState::WithoutEdid { name, state: _ } => OutputId::Name(name),
        }
    }
}

///////////////////////////////////////////////////////////////////////////////

/// State of a set of screen outputs and their positionning.
/// Intended to be stored in the database.
struct Layout {
    /// State of all connected outputs. Sorted by [`OutputId`].
    outputs: Box<[OutputState]>,
    /// Table of relations. Accessed by indexes from order in `self.outputs`.
    relations: RelationMatrix,
    /// Primary output if used / supported. Not in Wayland apparently.
    /// Used by some window manager to choose where to place tray icons, etc.
    /// Index is a reference in `self.outputs`.
    primary: Option<u32>,
}

// TODO it would be useful to store data for statistical mode, with output names
// Maybe clone of Layout with enum{Edid,OutputName} ?

impl Layout {
    fn new(mut outputs: Box<[OutputState]>) -> Layout {
        outputs.sort_unstable_by(|lhs, rhs| Ord::cmp(&lhs.id(), &rhs.id()));
        let size = NonZeroUsize::new(outputs.len()).expect("Layout must have one output");
        Layout {
            outputs,
            relations: RelationMatrix::new(size),
            primary: None, // FIXME
        }
    }
}

///////////////////////////////////////////////////////////////////////////////

#[derive(Debug)]
struct RelationMatrix {
    size: NonZeroUsize,
    /// `size * (size - 1) / 2` relations
    triangular_array: Box<[Option<Direction>]>,
}

impl RelationMatrix {
    pub fn new(size: NonZeroUsize) -> RelationMatrix {
        let n = size.get();
        let buffer_size = (n * (n - 1)) / 2;
        RelationMatrix {
            size,
            triangular_array: vec![None; buffer_size].into(),
        }
    }

    // index (x,y) -> (min,max), linearize to min*(min+1) + max or something
    // if swap must apply reversion to direction
    // TODO impl + tests
}
