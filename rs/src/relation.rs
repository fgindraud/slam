use std::cmp::Ordering;

/// For a binary relation *R*, describes `inverse(R(x,y)) = R(y,x)`.
pub trait InvertibleRelation {
    fn inverse(&self) -> Self;
}

/// Stores binary relations efficiently, like [`crate::geometry::Direction`].
/// Semantically a `Map<(usize,usize), Option<T>>`.
/// Relations are only stored for `lhs < rhs` and is reversed if necessary, all to avoid redundant data.
/// Relation with self are ignored, so it is not stored and always evaluate to [`None`].
/// Invalid indexes will usually trigger a [`panic!`].
/// Iteration on all pairs of indexes should iterate first on the high index and then low for performance.
#[derive(Debug, Clone)]
pub struct RelationMatrix<T> {
    size: usize,
    /// `size * (size - 1) / 2` relations
    array: Vec<Option<T>>,
}

/// Buffer size for triangular matrix : `n * (n-1) / 2`.
/// Except for `n = 0`, where buffer size is chosen to be 0.
fn buffer_size(nb_elements: usize) -> usize {
    // Clamp to 0 with saturating sub to prevent underflow.
    (nb_elements * nb_elements.saturating_sub(1)) / 2
}

impl<T> RelationMatrix<T> {
    /// Create an empty relation matrix with `size` elements.
    pub fn new(size: usize) -> RelationMatrix<T> {
        RelationMatrix {
            size,
            array: (0..buffer_size(size)).map(|_| None).collect(),
        }
    }

    pub fn size(&self) -> usize {
        self.size
    }

    /// Compute linearized index for `0 <= low < high < size`.
    /// Linearized layout : `[(0,1),(0-1,2),(0-2,3),(0-3,4),...]`.
    fn linearized_index(&self, low: usize, high: usize) -> usize {
        assert!(low < high, "expected {} < {}", low, high);
        assert!(high < self.size);
        let high_offset = (high * (high - 1)) / 2; // 0, 1, 3, 6, ...
        high_offset + low
    }
}
impl<T: Clone> RelationMatrix<T> {
    /// Add a new element with no relations to other, at the end of indexes.
    /// Returns the new index (equal to `size - 1`).
    pub fn add_element(&mut self) -> usize {
        let size = self.size;
        self.array.resize(buffer_size(size + 1), None);
        self.size = size + 1;
        size
    }

    /// Remove an element and all its relations.
    /// All elements with higher indexes will be shifted by `-1`.
    /// This matches use in compute_rects.
    pub fn remove_element(&mut self, index: usize) {
        assert!(index < self.size);
        // Shift values backward in holes left by removal in `self.array`.
        let mut dest_buffer_index = (index * (index.saturating_sub(1))) / 2;
        for high in (index + 1)..self.size {
            for low in 0..high {
                if low != index {
                    let src_buffer_index = self.linearized_index(low, high);
                    self.array[dest_buffer_index] = self.array[src_buffer_index].take();
                    dest_buffer_index += 1;
                }
            }
        }
        self.size -= 1;
        self.array.truncate(dest_buffer_index)
    }
}
impl<T: InvertibleRelation + Clone> RelationMatrix<T> {
    /// Get relation value for `(lhs, rhs)`.
    pub fn get(&self, lhs: usize, rhs: usize) -> Option<T> {
        match Ord::cmp(&lhs, &rhs) {
            Ordering::Less => self.array[self.linearized_index(lhs, rhs)].clone(),
            Ordering::Greater => self.array[self.linearized_index(rhs, lhs)]
                .as_ref()
                .map(|r| r.inverse()),
            Ordering::Equal => None,
        }
    }

    /// Set relation value for `(lhs, rhs)`.
    pub fn set(&mut self, lhs: usize, rhs: usize, relation: Option<T>) {
        match Ord::cmp(&lhs, &rhs) {
            Ordering::Less => {
                let index = self.linearized_index(lhs, rhs);
                self.array[index] = relation
            }
            Ordering::Greater => {
                let index = self.linearized_index(rhs, lhs);
                self.array[index] = relation.map(|r| r.inverse())
            }
            Ordering::Equal => (),
        }
    }

    /// Check if all outputs are connected by relations.
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
        let mut representatives = Vec::from_iter(0..self.size);
        // Start with all outputs as singular components. Merge them every time there is a relation.
        for rhs in 1..self.size {
            for lhs in 0..rhs {
                if self.get(lhs, rhs).is_some() {
                    // Merge connected components towards min index.
                    let lhs = get_representative(&representatives, lhs);
                    let rhs = get_representative(&representatives, rhs);
                    representatives[std::cmp::max(lhs, rhs)] = std::cmp::min(lhs, rhs)
                }
            }
        }
        // If all outputs form a single block, the representant of everyone should be 0 (smallest).
        (0..self.size).all(|output| get_representative(&representatives, output) == 0)
    }
}

// TODO serialization : just store linearized buffer, infer size with sqrt()

#[cfg(test)]
#[test]
fn test_relation_matrix_basic() {
    use crate::geometry::Direction;

    // Check buffer size
    assert_eq!(buffer_size(0), 0);
    assert_eq!(buffer_size(1), 0);
    assert_eq!(buffer_size(2), 1);
    assert_eq!(buffer_size(3), 3);
    // Basic ops
    let size = 10;
    let mut matrix = RelationMatrix::new(size);
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
    // Add some more content
    for (i, j) in [(0, 4), (4, 2), (2, 1), (1, 3)] {
        matrix.set(i, j, Some(Direction::LeftOf))
    }
    // Remove and check that the matrix are the same if we skip the removed id.
    let original = matrix.clone();
    let removed_id = 3;
    matrix.remove_element(removed_id);
    assert_eq!(matrix.array.len(), buffer_size(matrix.size));
    for lhs in 0..matrix.size {
        for rhs in 0..matrix.size {
            assert_eq!(
                matrix.get(lhs, rhs),
                original.get(
                    lhs + if lhs >= removed_id { 1 } else { 0 },
                    rhs + if rhs >= removed_id { 1 } else { 0 }
                )
            );
        }
    }
}

#[cfg(test)]
#[test]
fn test_relation_matrix_connexity() {
    use crate::geometry::Direction;

    fn check(n: usize, is_connex: bool, relations: &[(usize, usize)]) {
        let mut matrix = RelationMatrix::new(n);
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
    check(0, true, &[]);

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
