use super::RelationMatrix;
use crate::geometry::{Direction, Vec2d, Vec2di};
use std::cmp::Ordering;
use std::ops::{Add, RangeInclusive};

pub struct Infeasible;

pub fn compute_base_coordinates(
    sizes: &[Vec2di],
    relations: &RelationMatrix,
) -> Result<Vec<Vec2di>, Infeasible> {
    let n_outputs = sizes.len();
    assert_eq!(n_outputs, relations.size().get());
    // Start with biggest screen at pos (0,0), all others at unconstrained coordinates
    let mut problem = QpProblemState::default();
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
        problem.coordinate_definitions.push(definition);
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

#[derive(Debug, Default)]
struct QpProblemState {
    coordinate_definitions: Vec<Vec2d<Expression>>,
    variables: Vec<MonoVariableConstraint>,
}

impl QpProblemState {
    fn new_variable(&mut self) -> Variable {
        let index = self.variables.len();
        self.variables.push(MonoVariableConstraint::default());
        Variable { index }
    }

    fn add_equality_constraint(
        &mut self,
        lhs: Expression,
        rhs: Expression,
    ) -> Result<(), Infeasible> {
        match (lhs.variable, rhs.variable) {
            (None, None) => {
                if lhs.constant != rhs.constant {
                    Err(Infeasible)
                } else {
                    Ok(())
                }
            }
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
        let vid = variable.index;
        if !self.variables[vid].bounds.contains(&constant) {
            return Err(Infeasible);
        }
        // Remove the variable, shifting all higher ids by -1, and fix definitions
        self.variables.remove(vid);
        let fix_definition = |expr: &mut Expression| {
            if let Some(variable) = &mut expr.variable {
                if variable.index > vid {
                    variable.index -= 1;
                } else if variable.index == vid {
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
        let updated_kept_constraint = MonoVariableConstraint::merge(
            &self.variables[kept.index],
            &self.variables[removed.index].add(-kept_offset),
        );
        let (min, max) = updated_kept_constraint.bounds.clone().into_inner();
        match Ord::cmp(&min, &max) {
            Ordering::Less => (),
            Ordering::Greater => return Err(Infeasible),
            Ordering::Equal => {
                // min == kept == removed - kept_offset
                self.replace_variable_with_constant(removed, min + kept_offset)?;
                return self.replace_variable_with_constant(kept, min);
            }
        }
        self.variables[kept.index] = updated_kept_constraint;
        // Remove the variable, shifting all higher ids by -1, and fix definitions (removed -> kept + kept_offset)
        self.variables.remove(removed.index);
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

/// `min <= variable <= max`
#[derive(Debug, PartialEq, Eq)]
struct MonoVariableConstraint {
    bounds: RangeInclusive<i32>,
}

impl Default for MonoVariableConstraint {
    fn default() -> Self {
        MonoVariableConstraint {
            bounds: i32::MIN..=i32::MAX,
        }
    }
}

impl<'a> Add<i32> for &'a MonoVariableConstraint {
    type Output = MonoVariableConstraint;
    fn add(self, rhs: i32) -> MonoVariableConstraint {
        MonoVariableConstraint {
            bounds: RangeInclusive::new(
                self.bounds.start().saturating_add(rhs),
                self.bounds.end().saturating_add(rhs),
            ),
        }
    }
}

impl MonoVariableConstraint {
    fn merge(&self, other: &MonoVariableConstraint) -> MonoVariableConstraint {
        MonoVariableConstraint {
            bounds: RangeInclusive::new(
                std::cmp::max(*self.bounds.start(), *other.bounds.start()),
                std::cmp::min(*self.bounds.end(), *other.bounds.end()),
            ),
        }
    }
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

#[cfg(test)]
#[test]
fn test_qp_problem_replace_with_const() {
    let mut problem = QpProblemState::default();
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
    problem.variables[0].bounds = -10..=10;
    problem.variables[1].bounds = 0..=10;
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
    let mut problem = QpProblemState::default();
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
    problem.variables[1].bounds = -10..=10;
    problem.variables[2].bounds = -10..=10;
    problem.variables[3].bounds = 0..=10;
    problem.variables[4].bounds = 0..=10;
    // x = y + 10, {x,y} in [0,10] => x = 10, y = 0
    let result = problem.add_equality_constraint(
        problem.coordinate_definitions[2].x.clone(),
        problem.coordinate_definitions[2].y.clone() + 10,
    );
    assert!(result.is_ok());
    assert_eq!(problem.variables.len(), 3);
    assert_eq!(
        problem.coordinate_definitions[2].x,
        Expression::constant(10)
    );
    assert_eq!(problem.coordinate_definitions[2].y, Expression::constant(0));
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
    assert_eq!(problem.variables[0].bounds, -40..=-20);
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
