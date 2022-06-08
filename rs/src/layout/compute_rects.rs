use super::RelationMatrix;
use crate::geometry::{Direction, InvertibleRelation, Vec2d, Vec2di};
use std::cmp::Ordering;
use std::ops::Add;

pub struct Infeasible;

pub fn compute_base_coordinates(
    sizes: &[Vec2di],
    relations: &RelationMatrix<Direction>,
) -> Result<Vec<Vec2di>, Infeasible> {
    let n_outputs = sizes.len();
    assert_eq!(n_outputs, relations.size());
    // Start with biggest screen at pos (0,0), all others at unconstrained coordinates
    let mut problem = QpProblemState::new();
    let biggest_screen = sizes
        .iter()
        .enumerate()
        .max_by_key(|(_i, size)| size.x * size.y)
        .map(|(i, _size)| i)
        .expect("sizes not empty");
    for i in 0..n_outputs {
        let definition = if i != biggest_screen {
            Vec2d {
                x: Expression::free_variable(&mut problem),
                y: Expression::free_variable(&mut problem),
            }
        } else {
            Vec2d {
                x: Expression::constant(0),
                y: Expression::constant(0),
            }
        };
        problem.add_coordinate(definition);
    }
    //
    for rhs in 0..n_outputs {
        for lhs in 0..rhs {
            if let Some(relation) = relations.get(lhs, rhs) {
                let lhs_coord = problem.coordinate_definitions[lhs].clone();
                let rhs_coord = problem.coordinate_definitions[rhs].clone();
                match relation {
                    // TODO bi constraints for ortho direction
                    Direction::LeftOf => {
                        problem.add_equality_constraint(lhs_coord.x + sizes[lhs].x, rhs_coord.x)?
                    }
                    Direction::RightOf => {
                        problem.add_equality_constraint(lhs_coord.x, rhs_coord.x + sizes[rhs].x)?
                    }
                    Direction::Under => {
                        problem.add_equality_constraint(lhs_coord.y + sizes[lhs].y, rhs_coord.y)?
                    }
                    Direction::Above => {
                        problem.add_equality_constraint(lhs_coord.y, rhs_coord.y + sizes[rhs].y)?
                    }
                }
            }
        }
    }

    Ok(Vec::new())
}

#[derive(Debug)]
/// Stores, preprocess and simplify constraints. Goals :
/// - early detect of infeasible problems
/// - merge equal variables
///
/// Not done : simplify singleton constraints into constant.
/// Rationale : makes code too complex to be worth it, and done by the optimizer anyway.
struct QpProblemState {
    /// List of expression of coordinates values.
    coordinate_definitions: Vec<Vec2d<Expression>>,
    /// One entry per variable, with index == variable index.
    /// Thus this is the definition of the number of variables.
    /// Constraint : `min <= variable <= max`.
    mono_constraints: Vec<Constraint>,
    /// `min <= rhs - lhs <= max`. Also read as `lhs + min <= rhs <= lhs + max`.
    dual_constraints: RelationMatrix<Constraint>,
}

impl QpProblemState {
    fn new() -> QpProblemState {
        QpProblemState {
            coordinate_definitions: Vec::new(),
            mono_constraints: Vec::new(),
            dual_constraints: RelationMatrix::new(0),
        }
    }

    fn new_variable(&mut self) -> Variable {
        let index = self.mono_constraints.len();
        self.mono_constraints.push(Constraint::unconstrained());
        let dc_index = self.dual_constraints.add_element();
        debug_assert_eq!(dc_index, index);
        Variable { index }
    }

    fn nb_variables(&self) -> usize {
        self.mono_constraints.len()
    }

    fn add_coordinate(&mut self, definition: Vec2d<Expression>) {
        if let Some(v) = &definition.x.variable {
            assert!(v.index < self.nb_variables());
        }
        if let Some(v) = &definition.y.variable {
            assert!(v.index < self.nb_variables());
        }
        self.coordinate_definitions.push(definition)
    }

    fn add_equality_constraint(
        &mut self,
        lhs: Expression,
        rhs: Expression,
    ) -> Result<(), Infeasible> {
        match (lhs.variable, rhs.variable) {
            (None, None) => match lhs.constant == rhs.constant {
                true => Ok(()),
                false => Err(Infeasible),
            },
            (Some(var), None) => {
                self.replace_variable_with_constant(var, rhs.constant - lhs.constant)
            }
            (None, Some(var)) => {
                self.replace_variable_with_constant(var, lhs.constant - rhs.constant)
            }
            (Some(lhs_var), Some(rhs_var)) => {
                self.merge_variables(lhs_var, lhs.constant, rhs_var, rhs.constant)
            }
        }
    }

    /// `variable <- constant`
    fn replace_variable_with_constant(
        &mut self,
        variable: Variable,
        constant: i32,
    ) -> Result<(), Infeasible> {
        if !self.mono_constraints[variable.index].contains(constant) {
            return Err(Infeasible);
        }
        // Remove the variable, shifting all higher ids by -1, and fix definitions
        self.mono_constraints.remove(variable.index);
        let fix_definition = |expr: &mut Expression| {
            if let Some(expr_var) = &mut expr.variable {
                if expr_var.index > variable.index {
                    expr_var.index -= 1;
                } else if expr_var.index == variable.index {
                    expr.constant += constant;
                    expr.variable = None;
                }
            }
        };
        for definition in &mut self.coordinate_definitions {
            fix_definition(&mut definition.x);
            fix_definition(&mut definition.y);
        }
        // TODO multi constraints
        Ok(())
    }

    /// `lhs + offset = rhs + offset`
    fn merge_variables(
        &mut self,
        lhs: Variable,
        lhs_offset: i32,
        rhs: Variable,
        rhs_offset: i32,
    ) -> Result<(), Infeasible> {
        // Select kept variable, to substitute in the form `removed -> kept + kept_offset`.
        // Ensure removed index > kept index : no need to shift kept index references after removal.
        let (removed, kept, kept_offset) = match Ord::cmp(&lhs.index, &rhs.index) {
            Ordering::Less => (rhs, lhs, lhs_offset - rhs_offset),
            Ordering::Greater => (lhs, rhs, rhs_offset - lhs_offset),
            Ordering::Equal => {
                // Merge is either no-op or constraint failure.
                return match lhs_offset - rhs_offset {
                    0 => Ok(()),
                    _ => Err(Infeasible),
                };
            }
        };
        // Update variable constraints
        self.mono_constraints[kept.index] = Constraint::merge(
            &self.mono_constraints[kept.index],
            &self.mono_constraints[removed.index].add(-kept_offset),
        )?;
        // Remove the variable, shifting all higher ids by -1, and fix definitions (removed -> kept + kept_offset)
        self.mono_constraints.remove(removed.index);
        let fix_definition = |expr: &mut Expression| {
            if let Some(variable) = &mut expr.variable {
                if variable.index > removed.index {
                    variable.index -= 1;
                } else if variable.index == removed.index {
                    expr.constant += kept_offset;
                    expr.variable = Some(kept);
                }
            }
        };
        for definition in &mut self.coordinate_definitions {
            fix_definition(&mut definition.x);
            fix_definition(&mut definition.y);
        }
        // TODO multi constraints
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Variable {
    index: usize,
}

/// `constant [+ variable]`
#[derive(Debug, Clone, PartialEq, Eq)]
struct Expression {
    constant: i32,
    variable: Option<Variable>,
}

impl Expression {
    fn constant(value: i32) -> Expression {
        Expression {
            constant: value,
            variable: None,
        }
    }
    fn free_variable(problem: &mut QpProblemState) -> Expression {
        Expression {
            constant: 0,
            variable: Some(problem.new_variable()),
        }
    }
}

impl Add<i32> for Expression {
    type Output = Expression;
    fn add(mut self, rhs: i32) -> Expression {
        self.constant += rhs;
        self
    }
}

/// `min <= expr <= max`
#[derive(Debug, Clone, PartialEq, Eq)]
struct Constraint {
    min: i32,
    max: i32,
}

impl Constraint {
    fn new(min: i32, max: i32) -> Constraint {
        Constraint { min, max }
    }
    fn unconstrained() -> Constraint {
        Constraint::new(i32::MIN, i32::MAX)
    }

    fn contains(&self, value: i32) -> bool {
        self.min <= value && value <= self.max
    }
    fn is_unconstrained(&self) -> bool {
        self.min <= i32::MIN / 2 && self.max >= i32::MAX
    }

    fn merge(&self, other: &Constraint) -> Result<Constraint, Infeasible> {
        let min = std::cmp::max(self.min, other.min);
        let max = std::cmp::min(self.max, other.max);
        match Ord::cmp(&min, &max) {
            Ordering::Greater => Err(Infeasible),
            _ => Ok(Constraint { min, max }),
        }
    }
}

impl<'a> Add<i32> for &'a Constraint {
    type Output = Constraint;
    fn add(self, rhs: i32) -> Constraint {
        Constraint {
            min: self.min.saturating_add(rhs),
            max: self.max.saturating_add(rhs),
        }
    }
}

/// Only meaningful when used as dual constraint.
/// `min <= rhs - lhs <= max` <=> `-max <= lhs - rhs <= -min`.
impl InvertibleRelation for Constraint {
    fn inverse(&self) -> Self {
        Constraint {
            min: self.max.saturating_neg(),
            max: self.min.saturating_neg(),
        }
    }
}

#[cfg(test)]
#[test]
fn test_qp_problem_replace_with_const() {
    let mut problem = QpProblemState::new();
    let coord0 = Vec2d::new(
        Expression::free_variable(&mut problem) + 40, // index 0
        Expression::free_variable(&mut problem),      // index 1
    );
    let coord1 = Vec2d::new(
        Expression {
            constant: 0,
            variable: coord0.x.variable.clone(), // index 0 multi use
        },
        Expression::constant(42),
    );
    problem.coordinate_definitions = vec![coord0, coord1];
    problem.mono_constraints[0] = Constraint::new(-10, 10);
    problem.mono_constraints[1] = Constraint::new(0, 10);
    // successful replacement
    let replacement = problem.replace_variable_with_constant(Variable { index: 0 }, -10);
    assert!(replacement.is_ok());
    assert_eq!(
        problem.coordinate_definitions[0].x,
        Expression::constant(30)
    );
    assert_eq!(
        problem.coordinate_definitions[0].y,
        Expression {
            constant: 0,
            variable: Some(Variable { index: 0 }) // index shifted
        }
    );
    assert_eq!(
        problem.coordinate_definitions[1].x,
        Expression::constant(-10)
    );
    // failed replacement (bounds)
    let replacement = problem.replace_variable_with_constant(Variable { index: 0 }, -10);
    assert!(replacement.is_err());
}

#[cfg(test)]
#[test]
fn test_qp_problem_merge_variables() {
    let mut problem = QpProblemState::new();
    let coord0 = Vec2d::new(
        Expression::free_variable(&mut problem) + 40, // index 0
        Expression::free_variable(&mut problem),      // index 1
    );
    let coord1 = Vec2d::new(
        Expression {
            constant: 0,
            variable: coord0.x.variable.clone(), // index 0 multi use
        },
        Expression::free_variable(&mut problem), // index 2
    );
    let coord2 = Vec2d::new(
        Expression::free_variable(&mut problem), // index 3
        Expression::free_variable(&mut problem), // index 4
    );
    problem.coordinate_definitions = vec![coord0, coord1, coord2];
    problem.mono_constraints[1] = Constraint::new(-10, 10);
    problem.mono_constraints[2] = Constraint::new(-10, 10);
    problem.mono_constraints[3] = Constraint::new(0, 10);
    problem.mono_constraints[4] = Constraint::new(0, 10);
    // x = y + 10, {x,y} in [0,10] => x = 10, y = 0, but no simplification
    let result = problem.add_equality_constraint(
        problem.coordinate_definitions[2].x.clone(),
        problem.coordinate_definitions[2].y.clone() + 10,
    );
    assert!(result.is_ok());
    assert_eq!(
        problem.coordinate_definitions[2].x,
        Expression {
            constant: 0,
            variable: Some(Variable { index: 3 })
        }
    );
    assert_eq!(
        problem.coordinate_definitions[2].y,
        Expression {
            constant: -10,
            variable: Some(Variable { index: 3 })
        }
    );
    assert_eq!(
        problem.mono_constraints[3].min,
        problem.mono_constraints[3].max
    );
    // normal merge (0 with 1), shifts 2 -> 1.
    // (0) + 40 == (1) + 10. bounds of (0) infinite so just reuse ones from 1
    let result = problem.add_equality_constraint(
        problem.coordinate_definitions[0].x.clone(),
        problem.coordinate_definitions[0].y.clone() + 10,
    );
    assert!(result.is_ok());
    assert_eq!(
        problem.coordinate_definitions[0].x,
        Expression {
            constant: 40,
            variable: Some(Variable { index: 0 })
        }
    );
    assert_eq!(problem.mono_constraints[0], Constraint::new(-40, -20));
    assert_eq!(
        problem.coordinate_definitions[0].y,
        Expression {
            constant: 30,
            variable: Some(Variable { index: 0 })
        }
    );
    // failed merge
    let result = problem.add_equality_constraint(
        problem.coordinate_definitions[0].x.clone(),
        problem.coordinate_definitions[1].y.clone() + 100,
    );
    assert!(result.is_err())
}
