use crate::geometry::{Rect, Transform, Vec2di};
use crate::relation::RelationMatrix;

///////////////////////////////////////////////////////////////////////////////

/// Bytes 8 to 15 of EDID header, containing manufacturer id + serial number.
/// This should be sufficient for unique identification of a display.
#[derive(
    Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, serde::Serialize, serde::Deserialize,
)]
pub struct Edid(u64);

impl std::fmt::Debug for Edid {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "Edid({:#016x})", self.0)
    }
}

/// Build from raw full EDID data.
impl<'a> TryFrom<&'a [u8]> for Edid {
    type Error = &'static str;
    fn try_from(edid_entry_bytes: &'a [u8]) -> Result<Edid, &'static str> {
        if !(edid_entry_bytes.len() >= 16) {
            // Very permissive here as we only need the bytes 8-15.
            // EDID standard has at least 128 bytes from 1.0 upwards.
            return Err("Edid: bad length");
        }
        if edid_entry_bytes[0..8] != [0x0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x0] {
            return Err("Edid: missing constant header pattern");
        }
        let id_bytes: [u8; 8] = edid_entry_bytes[8..16].try_into().unwrap();
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

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, serde::Serialize, serde::Deserialize)]
pub struct Mode {
    pub size: Vec2di,
    pub frequency: u32,
}

///////////////////////////////////////////////////////////////////////////////

/// Identifier for an output
#[derive(
    Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, serde::Serialize, serde::Deserialize,
)]
pub enum OutputId {
    /// [`Edid`] is prefered if available
    Edid(Edid),
    /// Fallback to output name
    Name(String),
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, serde::Serialize, serde::Deserialize)]
pub enum OutputState {
    Disabled,
    Enabled {
        mode: Mode,
        transform: Transform,
        bottom_left: Vec2di,
    },
}

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

    fn is_enabled(&self) -> bool {
        match self {
            Self::Enabled { .. } => true,
            Self::Disabled => false,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, serde::Serialize, serde::Deserialize)]
pub struct OutputEntry {
    pub id: OutputId,
    pub state: OutputState,
}

/// State of a set of screen outputs and their positionning.
/// Intended to be stored in the database.
/// Lists all connected outputs of a system.
/// Positions are defined by coordinates of the bottom left corner, starting at `(0,0)`.
///
/// It is allowed to have multiple identical [`Edid`] if an output is connected by multiple means.
/// However it must only be enabled once, or the layout is unsupported.
/// Backend will expect an Edid to only be enabled once.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Layout {
    /// Sorted by [`OutputId`].
    #[serde(deserialize_with = "deserialize_layout_entries")]
    outputs: Box<[OutputEntry]>,
    /// Primary output if used / supported. Not in Wayland apparently.
    /// Used by some window manager to choose where to place tray icons, etc.
    primary: Option<OutputId>,
}

impl Layout {
    /// Return the list of outputs ids, sorted.
    pub fn connected_outputs<'l>(
        &'l self,
    ) -> impl Iterator<Item = &'l OutputId> + ExactSizeIterator + DoubleEndedIterator {
        self.outputs.iter().map(|o| &o.id)
    }
}

///////////////////////////////////////////////////////////////////////////////

bitflags::bitflags! {
    pub struct UnsupportedCauses: u8 {
        /// Some output rects overlap
        const OVERLAPS = 0b00000001;
        /// Output rects are not all connected to each other
        const GAPS = 0b00000010;
        /// Using clone mode
        const CLONES = 0b00000100;
        /// Output [`Edid`] enabled more than once
        const DUPLICATED_ENABLED_EDID = 0b00001000;
    }
}

/// Result of trying to validate layout output entries.
/// We need both the layout info and the error status, thus the choice of struct instead of [`Result`].
#[derive(Debug)]
pub struct LayoutInfo {
    pub layout: Layout,
    pub unsupported_causes: UnsupportedCauses,
    // TODO it would be useful to store data for statistical mode, with output names
}

impl LayoutInfo {
    /// primary is supposed to point to a connected and enabled output (not checked)
    pub fn from(mut outputs: Vec<OutputEntry>, primary: Option<OutputId>) -> LayoutInfo {
        outputs.sort();
        normalize_bottom_left_coordinates(&mut outputs);
        let unsupported_causes = check_entries_for_unsupported_causes(&outputs);
        let layout = Layout {
            outputs: Vec::into_boxed_slice(outputs),
            primary,
        };
        LayoutInfo {
            layout,
            unsupported_causes,
        }
    }

    pub fn from_iter<I: IntoIterator<Item = OutputEntry>>(
        iter: I,
        primary: Option<OutputId>,
    ) -> Self {
        LayoutInfo::from(Vec::from_iter(iter), primary)
    }
}

/// Validate and normalize layout contents in deserialization case.
fn deserialize_layout_entries<'de, D>(deserializer: D) -> Result<Box<[OutputEntry]>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let mut entries: Box<[OutputEntry]> = serde::Deserialize::deserialize(deserializer)?;
    entries.sort();
    normalize_bottom_left_coordinates(&mut entries);
    let unsupported = check_entries_for_unsupported_causes(&entries);
    if unsupported != UnsupportedCauses::empty() {
        use serde::de::Error;
        Err(D::Error::custom(format!(
            "unsupported layout: {:?}",
            unsupported
        )))
    } else {
        Ok(entries)
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

/// Check output entries for problems:
/// - gaps and overlaps between enabled outputs rects
fn check_entries_for_unsupported_causes(outputs: &[OutputEntry]) -> UnsupportedCauses {
    let mut unsupported_causes = UnsupportedCauses::empty();

    // Coordinate problems : gaps, overlap
    let rects = Vec::from_iter(outputs.iter().filter_map(|o| o.state.rect()));
    let size = rects.len();
    let mut relations = RelationMatrix::new(size);
    for rhs in 1..size {
        let rhs_rect = &rects[rhs];
        for lhs in 0..rhs {
            let lhs_rect = &rects[lhs];
            if lhs_rect.overlaps(rhs_rect) {
                unsupported_causes |= UnsupportedCauses::OVERLAPS;
            }
            relations.set(lhs, rhs, Rect::adjacent_direction(lhs_rect, rhs_rect))
        }
    }
    if !relations.is_single_connected_component() {
        unsupported_causes |= UnsupportedCauses::GAPS
    }

    // Duplicate enabled EDID
    let mut entries = outputs.into_iter();
    if let Some(first_entry) = entries.next() {
        let mut prev_id = &first_entry.id;
        let mut any_enabled_entry_with_prev_id = first_entry.state.is_enabled();

        for entry in entries {
            let enabled = entry.state.is_enabled();
            if &entry.id == prev_id {
                // Fail if id is enabled twice or more
                if any_enabled_entry_with_prev_id && enabled {
                    unsupported_causes |= UnsupportedCauses::DUPLICATED_ENABLED_EDID;
                    break;
                }
                any_enabled_entry_with_prev_id = any_enabled_entry_with_prev_id || enabled
            } else {
                // New id, just track new group
                prev_id = &entry.id;
                any_enabled_entry_with_prev_id = enabled;
            }
        }
    }

    unsupported_causes
}
