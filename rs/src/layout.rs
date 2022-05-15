use crate::geometry::{self, Direction, Rect, Transform, Vec2d};
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

#[derive(PartialEq, Eq, PartialOrd, Ord)]
pub enum OutputIdRef<'a> {
    Edid(Edid),
    Name(&'a str),
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
// TODO serialization

impl EnabledOutput {
    /// Get matching [`OutputId`].
    pub fn id(&self) -> OutputId {
        match self {
            EnabledOutput::Edid { edid, .. } => OutputId::Edid(edid.clone()),
            EnabledOutput::Name { name, .. } => OutputId::Name(name.clone()),
        }
    }

    fn id_ref<'a>(&'a self) -> OutputIdRef<'a> {
        match self {
            EnabledOutput::Edid { edid, .. } => OutputIdRef::Edid(edid.clone()),
            EnabledOutput::Name { name, .. } => OutputIdRef::Name(name.as_ref()),
        }
    }
}

impl Layout {
    /// Return the list of outputs ids, sorted.
    pub fn connected_outputs(&self) -> Box<[OutputId]> {
        let mut v = Vec::from_iter(Iterator::chain(
            self.disabled_outputs.iter().cloned(),
            self.enabled_outputs.iter().map(EnabledOutput::id),
        ));
        v.sort_unstable();
        Vec::into_boxed_slice(v)
    }

    /// Infer a layout from output coordinates.
    pub fn from_output_and_rects(
        disabled_outputs: Box<[OutputId]>,
        enabled_output_and_rects: Vec<(EnabledOutput, Rect)>,
    ) -> Result<Layout, LayoutInferenceError> {
        // Detect mode / coordinate mismatch
        for (output, rect) in enabled_output_and_rects.iter() {
            if let EnabledOutput::Edid { mode, .. } = output {
                if mode.size != rect.size {
                    return Err(LayoutInferenceError::ModeDoesNotMatchSize);
                }
            }
        }
        // Sort outputs and rects together then split them
        let mut enabled_output_and_rects = enabled_output_and_rects;
        enabled_output_and_rects
            .sort_unstable_by(|(l, _), (r, _)| std::cmp::Ord::cmp(&l.id_ref(), &r.id_ref()));
        let (enabled_outputs, rects): (Vec<_>, Vec<_>) =
            enabled_output_and_rects.into_iter().unzip();
        // Infer relations and check layout
        let size = rects.len();
        let mut relations = RelationMatrix::new(
            NonZeroUsize::new(size).ok_or(LayoutInferenceError::NoEnabledOutput)?,
        );
        for lhs_id in 0..size {
            let lhs_rect = &rects[lhs_id];
            for rhs_id in (lhs_id + 1)..size {
                let rhs_rect = &rects[rhs_id];
                if lhs_rect.overlaps(rhs_rect) {
                    return Err(LayoutInferenceError::Overlap);
                }
                relations.set(lhs_id, rhs_id, Rect::adjacent_direction(lhs_rect, rhs_rect))
            }
        }
        if !relations.is_single_connected_component() {
            return Err(LayoutInferenceError::Gaps);
        }
        Ok(Layout {
            disabled_outputs,
            enabled_outputs: Vec::into_boxed_slice(enabled_outputs),
            relations,
            primary: None, // FIXME
        })
    }
}

#[derive(Debug)]
pub enum LayoutInferenceError {
    NoEnabledOutput,
    Overlap,
    Gaps,
    ModeDoesNotMatchSize,
}
impl std::fmt::Display for LayoutInferenceError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        use LayoutInferenceError::*;
        let s = match self {
            NoEnabledOutput => "no enabled output",
            Overlap => "some outputs overlap",
            Gaps => "output set does not form a connex block",
            ModeDoesNotMatchSize => "output mode size does not match rect size",
        };
        s.fmt(f)
    }
}
impl std::error::Error for LayoutInferenceError {}

impl Layout {
    pub fn compute_rects(&self, enabled_output_preferred_modes: &[Mode]) -> Vec<Rect> {
        use good_lp::{Expression, IntoAffineExpression};
        let n_outputs = self.enabled_outputs.len();
        assert!(enabled_output_preferred_modes.len() == n_outputs);
        // Use preferred mode size when Edid is not available
        let output_sizes = Vec::from_iter(self.enabled_outputs.iter().enumerate().map(
            |(i, output)| match output {
                EnabledOutput::Edid { mode, .. } => mode.size.clone(),
                EnabledOutput::Name { .. } => enabled_output_preferred_modes[i].size.clone(),
            },
        ));
        // Create affine expressions for base coordinates that will be filled later.
        let mut coordinates: Vec<Option<(Expression, Expression)>> = vec![None; n_outputs];
        let mut outputs_to_see = std::collections::VecDeque::with_capacity(n_outputs);
        let mut relations = self.relations.clone();
        // Start with biggest screen, at pos (0,0)
        let biggest_screen = match output_sizes
            .iter()
            .enumerate()
            .max_by_key(|(_i, size)| size.x * size.y)
        {
            Some((i, _)) => i,
            None => unreachable!(),
        };
        coordinates[biggest_screen] = Some((Expression::from(0), Expression::from(0)));
        outputs_to_see.push_back(biggest_screen);
        //
        let mut problem = good_lp::ProblemVariables::new();
        while let Some(left) = outputs_to_see.pop_front() {
            // Process relations to neighbors
            for right in 0..n_outputs {
                if let Some(relation) = relations.get(left, right) {
                    if let Some(_) = coordinates[right] {
                        // Already defined coords, add constraints
                    } else {
                        // Defined coords for right
                        let left_coord = coordinates[left].as_ref().unwrap();
                        let right_coord = match relation {
                            Direction::LeftOf => (
                                left_coord.0.clone() + output_sizes[left].x,
                                problem.add_variable().into_expression(),
                            ),
                            _ => todo!(),
                        };
                    }
                }
            }
        }
        Vec::new()
    }
}

///////////////////////////////////////////////////////////////////////////////

/// Stores directional relations efficiently.
/// Semantically a `Map<(usize,usize), Option<Direction>>`.
/// Directions are only stored for `lhs < rhs` and is reversed if necessary, all to avoid redundant data.
/// Relation of a screen with itself makes no sense, so it is not stored and always evaluate to [`None`].
/// Invalid indexes will trigger a [`panic!`].
#[derive(Debug, Clone)]
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

    pub fn is_single_connected_component(&self) -> bool {
        // Union find structure with indexes : map[0..size] -> 0..size
        fn get_representative(map: &[usize], i: usize) -> usize {
            let mut result = i;
            loop {
                let repr = map[result];
                if repr == result {
                    return result;
                }
                result = repr
            }
        }
        let size = self.size().get();
        let mut representatives = Vec::from_iter(0..size);
        // Start with all outputs as singular components. Merge them every time there is a relation.
        for lhs in 0..size {
            for rhs in (lhs + 1)..size {
                if self.get(lhs, rhs).is_some() {
                    // Merge connected components towards min index.
                    let lhs = get_representative(&representatives, lhs);
                    let rhs = get_representative(&representatives, rhs);
                    representatives[std::cmp::max(lhs, rhs)] = std::cmp::min(lhs, rhs)
                }
            }
        }
        // If all outputs form a single block, the representant of everyone should be 0 (smallest).
        (0..size).all(|output| get_representative(&representatives, output) == 0)
    }

    // TODO serialization : just store linearized buffer, infer size with sqrt()
}

#[cfg(test)]
#[test]
fn test_relation_matrix_basic() {
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
    assert_eq!(matrix.get(2, 3), Some(Direction::Under))
}

#[cfg(test)]
#[test]
fn test_relation_matrix_connexity() {
    fn check(n: usize, is_connex: bool, relations: &[(usize, usize)]) {
        let mut matrix = RelationMatrix::new(NonZeroUsize::new(n).unwrap());
        for (i, j) in relations {
            // direction itself does not matter
            matrix.set(*i, *j, Some(Direction::LeftOf))
        }
        assert!(
            matrix.is_single_connected_component() == is_connex,
            "case: n={} rels={:?}",
            n,
            relations
        )
    }
    check(1, true, &[]);

    check(2, false, &[]);
    check(2, true, &[(0, 1)]);

    check(3, false, &[]);
    check(3, false, &[(0, 1)]);
    check(3, false, &[(0, 2)]);
    check(3, false, &[(1, 2)]);
    check(3, true, &[(1, 2), (0, 1)]);
    check(3, true, &[(0, 2), (0, 1)]);
    check(3, true, &[(0, 1), (1, 2), (0, 2)]);

    check(4, false, &[(0, 1), (1, 2), (0, 2)]);
    check(4, false, &[(0, 1), (2, 3)]);
    check(4, false, &[(0, 2), (1, 3)]);
    check(4, false, &[(0, 3), (1, 2)]);
    check(4, true, &[(0, 3), (1, 2), (0, 2)]);
    check(4, true, &[(0, 1), (1, 2), (2, 3)]);
    check(4, true, &[(0, 2), (3, 2), (1, 3)]);

    check(5, false, &[(0, 1), (1, 2), (2, 1), (3, 4)]);
    check(5, true, &[(0, 1), (1, 2), (2, 3), (3, 4)]);
    check(5, true, &[(0, 4), (4, 2), (2, 1), (1, 3)]);
}
