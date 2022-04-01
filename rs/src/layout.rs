use crate::geometry::{Direction, Rect, Transform, Vec2d};
use std::num::NonZeroUsize;

///////////////////////////////////////////////////////////////////////////////

/// Bytes 8 to 15 of EDID header, containing manufacturer id + serial number.
/// This should be sufficient for unique identification of a display.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Edid([u8; 8]);

impl std::fmt::Debug for Edid {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "Edid({:#016x})", u64::from_be_bytes(self.0))
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
        let mut id_bytes: [u8; 8] = Default::default();
        id_bytes.copy_from_slice(&bytes[8..16]);
        Ok(Edid(id_bytes))
    }
}

///////////////////////////////////////////////////////////////////////////////

#[derive(Debug, Clone)]
pub struct Mode {
    pub size: Vec2d,
    pub frequency: f64, // FIXME
}

/// Identifier for an output : [`Edid`] if available, or the output name.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]

pub enum OutputId {
    Edid(Edid),
    Name(String),
}

/// State and identification for an enabled output.
/// Two modes depending on whether an [`Edid`] is available :
/// - with [`Edid`] as an index : orientation and specific [`Mode`].
/// - fallback using output name, and do not store mode as we cannot differentiate monitors.
#[derive(Debug)]
pub enum EnabledOutput {
    Edid {
        edid: Edid,
        transform: Transform,
        mode: Mode,
    },
    Name {
        name: String,
        transform: Transform,
    },
}

/// State of a set of screen outputs and their relative positionning.
/// Intended to be stored in the database.
/// Lists all connected outputs of a system.
/// At least one output must be enabled.
#[derive(Debug)]
pub struct Layout {
    /// Disabled outputs : only list their ids.
    disabled_outputs: Box<[OutputId]>,
    /// Enabled output states.
    enabled_outputs: Box<[EnabledOutput]>,
    /// Relative positionning of the enabled outputs. Indexed by position of outputs in `enabled_outputs`.
    relations: RelationMatrix,
    /// Primary output if used / supported. Not in Wayland apparently.
    /// Used by some window manager to choose where to place tray icons, etc.
    /// Index is a reference in `enabled_outputs`.
    primary: Option<u16>,
}

// TODO it would be useful to store data for statistical mode, with output names
// Maybe clone of Layout with enum{Edid,OutputName} ?
// TODO serialization

impl EnabledOutput {
    /// Get matching [`OutputId`].
    pub fn id(&self) -> OutputId {
        match self {
            EnabledOutput::Edid { edid, .. } => OutputId::Edid(edid.clone()),
            EnabledOutput::Name { name, .. } => OutputId::Name(name.clone()),
        }
    }
}

impl Layout {
    pub fn from_output_and_rects(
        disabled_outputs: Box<[OutputId]>,
        enabled_output_and_rects: impl Iterator<Item = (EnabledOutput, Rect)>,
    ) -> Result<Layout, &'static str> {
        let (enabled_outputs, rects): (Vec<_>, Vec<_>) = enabled_output_and_rects.unzip();

        let size = rects.len();
        let mut relations = RelationMatrix::new(
            NonZeroUsize::new(size).ok_or("Layout must have one enabled output")?,
        );
        for lhs_id in 0..size {
            let lhs_rect = &rects[lhs_id];
            for rhs_id in (lhs_id + 1)..size {
                let rhs_rect = &rects[rhs_id];
                // TODO reject overlap ; covers both clones and weird layouts
                // TODO get adjacent directions
                // TODO check connexity : reject gaps
            }
        }

        Ok(Layout {
            disabled_outputs,
            enabled_outputs: Vec::into_boxed_slice(enabled_outputs),
            relations,
            primary: None, // FIXME
        })
    }

    /// Return the list of outputs ids, sorted.
    pub fn connected_outputs(&self) -> Box<[OutputId]> {
        let mut v = Vec::from_iter(Iterator::chain(
            self.disabled_outputs.iter().cloned(),
            self.enabled_outputs.iter().map(EnabledOutput::id),
        ));
        v.sort_unstable();
        Vec::into_boxed_slice(v)
    }
}

///////////////////////////////////////////////////////////////////////////////

/// Stores directional relations efficiently.
/// Semantically a `Map<(usize,usize), Option<Direction>>`.
/// Directions are only stored for `lhs < rhs` and is reversed if necessary, all to avoid redundant data.
/// Relation of a screen with itself makes no sense, so it is not stored and always evaluate to [`None`].
/// Invalid indexes will trigger a [`panic!`].
#[derive(Debug)]
pub struct RelationMatrix {
    size: NonZeroUsize,
    /// `size * (size - 1) / 2` relations
    array: Box<[Option<Direction>]>,
}

impl RelationMatrix {
    pub fn new(size: NonZeroUsize) -> RelationMatrix {
        let n = size.get();
        let buffer_size = (n * (n - 1)) / 2;
        RelationMatrix {
            size,
            array: vec![None; buffer_size].into(),
        }
    }

    pub fn size(&self) -> NonZeroUsize {
        self.size
    }

    /// Compute linearized index for `0 <= low < high < size`.
    /// Linearized layout : `[(0,1),(0-1,2),(0-2,3),(0-3,4),...]`.
    fn linearized_index(&self, low: usize, high: usize) -> usize {
        assert!(low < high, "expected {} < {}", low, high);
        assert!(high < self.size.get());
        let high_offset = (high * (high - 1)) / 2; // 0, 1, 3, 6, ...
        high_offset + low
    }

    pub fn get(&self, lhs: usize, rhs: usize) -> Option<Direction> {
        match (lhs, rhs) {
            (lhs, rhs) if lhs < rhs => self.array[self.linearized_index(lhs, rhs)],
            (lhs, rhs) if lhs > rhs => {
                self.array[self.linearized_index(rhs, lhs)].map(|d| d.inverse())
            }
            _ => None,
        }
    }

    pub fn set(&mut self, lhs: usize, rhs: usize, relation: Option<Direction>) {
        match (lhs, rhs) {
            (lhs, rhs) if lhs < rhs => self.array[self.linearized_index(lhs, rhs)] = relation,
            (lhs, rhs) if lhs > rhs => {
                self.array[self.linearized_index(rhs, lhs)] = relation.map(|d| d.inverse())
            }
            _ => (),
        }
    }

    // TODO serialization : just store linearized buffer, infer size with sqrt()
}

#[cfg(test)]
#[test]
fn test_relation_map() {
    let size = 10;
    let mut matrix = RelationMatrix::new(NonZeroUsize::new(size).unwrap());
    // Check linearization
    {
        let mut manual_offset = 0;
        for n in 1..size {
            for m in 0..n {
                assert_eq!(matrix.linearized_index(m, n), manual_offset);
                manual_offset += 1;
            }
        }
        assert_eq!(manual_offset, matrix.array.len())
    }
    // Sanity check for store/load logic
    matrix.set(2, 3, Some(Direction::LeftOf));
    assert_eq!(matrix.get(2, 3), Some(Direction::LeftOf));
    assert_eq!(matrix.get(3, 2), Some(Direction::RightOf));
    matrix.set(3, 2, Some(Direction::Above));
    assert_eq!(matrix.get(2, 3), Some(Direction::Under));
}
