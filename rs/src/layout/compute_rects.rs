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
                // TODO
                match relation {
                    Direction::LeftOf => (),
                    _ => todo!(),
                }
            }
        }
    }

    Ok(Vec::new())
}

#[derive(Default)]
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
        match (&lhs.variable, &rhs.variable) {
            (None, None) => {
                if lhs.constant != rhs.constant {
                    Err(Infeasible)
                } else {
                    Ok(())
                }
            }
            (Some(var), None) => {
                self.replace_variable_with_constant(*var, rhs.constant - lhs.constant)
            }
            (None, Some(var)) => {
                self.replace_variable_with_constant(*var, lhs.constant - rhs.constant)
            }
            (Some(lhs_var), Some(rhs_var)) => {
                self.merge_variables(*lhs_var, lhs.constant, *rhs_var, rhs.constant)
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
                    expr.variable = Some(kept.clone());
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
#[derive(Clone)]
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

impl Add<i32> for &Expression {
    type Output = Expression;
    fn add(self, rhs: i32) -> Expression {
        Expression {
            constant: self.constant + rhs,
            variable: self.variable.clone(),
        }
    }
}
