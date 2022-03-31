use crate::geometry::{Direction, Transform, Vec2d};
use std::num::NonZeroUsize;

///////////////////////////////////////////////////////////////////////////////

/// Bytes 8 to 15 of EDID header, containing manufacturer id + serial number.
/// This should be sufficient for unique identification of a display.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Edid([u8; 8]);

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
pub enum OutputState {
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
pub enum OutputWithEdidState {
    Disabled,
    Enabled { transform: Transform, mode: Mode },
}
#[derive(Debug)]
pub enum OutputWithoutEdidState {
    Disabled,
    Enabled { transform: Transform },
}

#[derive(Debug, Clone)]
pub struct Mode {
    pub size: Vec2d,
    pub frequency: f64, // FIXME
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
#[derive(Debug)]
pub struct Layout {
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
// TODO serialization

impl Layout {
    pub fn new(mut outputs: Box<[OutputState]>) -> Result<Layout, &'static str> {
        outputs.sort_unstable_by(|lhs, rhs| Ord::cmp(&lhs.id(), &rhs.id()));
        let size = NonZeroUsize::new(outputs.len()).ok_or("Layout must have one output")?;
        Ok(Layout {
            outputs,
            relations: RelationMatrix::new(size),
            primary: None, // FIXME
        })
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
