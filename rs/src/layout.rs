use crate::geometry::{Rect, Transform, Vec2di};
use crate::relation::RelationMatrix;

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

/// Identifier for an output
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub enum OutputId {
    /// [`Edid`] is prefered if available
    Edid(Edid),
    /// Fallback to output name
    Name(String),
}

#[derive(Debug)]
pub enum OutputState {
    Disabled,
    Enabled {
        mode: Mode,
        transform: Transform,
        bottom_left: Vec2di,
    },
}

#[derive(Debug)]
pub struct OutputEntry {
    pub id: OutputId,
    pub state: OutputState,
}

/// State of a set of screen outputs and their positionning.
/// Intended to be stored in the database.
/// Lists all connected outputs of a system.
/// Positions are defined by coordinates of the bottom left corner, starting at (0,0).
#[derive(Debug)]
pub struct Layout {
    /// Sorted by [`OutputId`].
    outputs: Box<[OutputEntry]>,
    /// Primary output if used / supported. Not in Wayland apparently.
    /// Used by some window manager to choose where to place tray icons, etc.
    /// Index is a reference in `enabled_outputs`.
    primary: Option<u16>,
    /// Status : supported, or not with the reason.
    status: LayoutStatus,
}

#[derive(Debug, Clone)]
pub enum LayoutStatus {
    /// Layout is usable, no gaps, no clones, no overlaps
    Supported,
    /// Unsupported due to overlaps
    Overlap,
    /// Unsupported due to gaps
    Gaps,
}

// TODO it would be useful to store data for statistical mode, with output names
// TODO serialization

impl OutputState {
    /// Rect occupied by monitor in abstract 2D space (X11 screen)
    fn rect(&self) -> Option<Rect> {
        match self {
            Self::Disabled => None,
            Self::Enabled {
                bottom_left,
                mode,
                transform,
            } => Some(Rect {
                bottom_left: bottom_left.clone(),
                size: mode.size.clone().apply(transform),
            }),
        }
    }
}

impl From<Vec<OutputEntry>> for Layout {
    fn from(mut outputs: Vec<OutputEntry>) -> Layout {
        outputs.sort_by(|lhs, rhs| Ord::cmp(&lhs.id, &rhs.id));
        normalize_bottom_left_coordinates(&mut outputs);
        let status = check_for_overlap_and_gaps(&outputs);
        Layout {
            outputs: Vec::into_boxed_slice(outputs),
            primary: None, // TODO way to fill this
            status,        // TODO provide other types of errors
        }
    }
}

impl FromIterator<OutputEntry> for Layout {
    fn from_iter<I: IntoIterator<Item = OutputEntry>>(iter: I) -> Self {
        Layout::from(Vec::from_iter(iter))
    }
}

impl Layout {
    /// Return the list of outputs ids, sorted.
    pub fn connected_outputs<'l>(
        &'l self,
    ) -> impl Iterator<Item = &'l OutputId> + ExactSizeIterator + DoubleEndedIterator {
        self.outputs.iter().map(|o| &o.id)
    }

    pub fn status(&self) -> LayoutStatus {
        self.status.clone()
    }
}

/// Renormalize coordinates to fit `Rect { (0, 0), (max_x, max_y) }`
fn normalize_bottom_left_coordinates(outputs: &mut [OutputEntry]) {
    let min_coords = outputs
        .iter()
        .fold(Vec2di::default(), |min, output| match &output.state {
            OutputState::Enabled { bottom_left, .. } => Vec2di::cwise_min(min, bottom_left.clone()),
            OutputState::Disabled => min,
        });
    for output in outputs {
        if let OutputState::Enabled { bottom_left, .. } = &mut output.state {
            *bottom_left -= min_coords
        }
    }
}

/// Check gaps and overlaps between enabled outputs rects
fn check_for_overlap_and_gaps(outputs: &[OutputEntry]) -> LayoutStatus {
    let rects = Vec::from_iter(outputs.iter().filter_map(|o| o.state.rect()));
    let size = rects.len();
    let mut relations = RelationMatrix::new(size);
    for rhs in 1..size {
        let rhs_rect = &rects[rhs];
        for lhs in 0..rhs {
            let lhs_rect = &rects[lhs];
            if lhs_rect.overlaps(rhs_rect) {
                return LayoutStatus::Overlap;
            }
            relations.set(lhs, rhs, Rect::adjacent_direction(lhs_rect, rhs_rect))
        }
    }
    if relations.is_single_connected_component() {
        LayoutStatus::Supported
    } else {
        LayoutStatus::Gaps
    }
}
