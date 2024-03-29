use super::RelationMatrix;
use crate::geometry::{Direction, InvertibleRelation, Rect, Vec2d, Vec2di};
use std::cmp::Ordering;
use std::ops::{Add, AddAssign, Mul};
use std::time::Duration;

#[derive(Debug)]
pub struct Infeasible;

/// Compute output `bottom_left` coords as an optimization problem with constraints coming from a [`RelationMatrix`].
/// May fail if constraints cannot be met.
pub fn compute_optimized_bottom_left_coords(
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
                match relation {
                    Direction::LeftOf => add_leftof_relation(&mut problem, lhs, rhs, &sizes)?,
                    Direction::RightOf => add_leftof_relation(&mut problem, rhs, lhs, &sizes)?,
                    Direction::Under => add_under_relation(&mut problem, lhs, rhs, &sizes)?,
                    Direction::Above => add_under_relation(&mut problem, rhs, lhs, &sizes)?,
                }
            }
        }
    }
    // TODO maybe post simplify singleton constraints
    let settings = osqp::Settings::default()
        .verbose(false)
        .time_limit(Some(Duration::from_secs(1)));
    let mut qp_problem = create_qp_problem(&problem, sizes, &settings).map_err(|_| Infeasible)?;
    let solution = match qp_problem.solve() {
        osqp::Status::Solved(solution) => solution,
        unsolved => {
            use osqp::Status::*;
            match unsolved {
                SolvedInaccurate(_) => log::info!("osqp: problem solved but inaccurate"),
                TimeLimitReached(_) => log::info!("osqp: time limit reached"),
                MaxIterationsReached(_) => log::info!("osqp: max iterations reached"),
                PrimalInfeasible(_) => log::debug!("osqp: primal infeasible"),
                PrimalInfeasibleInaccurate(_) => log::debug!("osqp: primal infeasible inaccurate"),
                DualInfeasible(_) => log::debug!("osqp: dual infeasible"),
                DualInfeasibleInaccurate(_) => log::debug!("osqp: dual infeasible inaccurate"),
                NonConvex(_) => log::debug!("osqp: non convex"),
                _ => {}
            }
            return Err(Infeasible);
        }
    };
    // Extract results. For now just round floats into integers.
    problem
        .coordinate_definitions
        .iter()
        .map(|def| -> Result<Vec2di, Infeasible> {
            Ok(Vec2di {
                x: def.x.evaluate(solution.x())?,
                y: def.y.evaluate(solution.x())?,
            })
        })
        .collect()
}

// Helpers that are used twice each (LeftOf+RightOf, Above+Under)
fn add_leftof_relation(
    problem: &mut QpProblemState,
    left: usize,
    right: usize,
    sizes: &[Vec2di],
) -> Result<(), Infeasible> {
    // left.x + left.sx = right.x
    problem.add_equality_constraint(
        problem.coordinate_definitions[left].x.clone() + sizes[left].x,
        problem.coordinate_definitions[right].x.clone(),
    )?;
    // left.y - right.sy <= right.y <= left.y + lhs.sy
    problem.add_dual_constraint(
        problem.coordinate_definitions[left].y.clone(),
        problem.coordinate_definitions[right].y.clone(),
        Constraint::new(-sizes[right].y, sizes[left].y),
    )
}
fn add_under_relation(
    problem: &mut QpProblemState,
    under: usize,
    above: usize,
    sizes: &[Vec2di],
) -> Result<(), Infeasible> {
    // under.y + under.sy = above.y
    problem.add_equality_constraint(
        problem.coordinate_definitions[under].y.clone() + sizes[under].y,
        problem.coordinate_definitions[above].y.clone(),
    )?;
    // under.x - above.sx <= above.x <= under.x + under.sx
    problem.add_dual_constraint(
        problem.coordinate_definitions[under].x.clone(),
        problem.coordinate_definitions[above].x.clone(),
        Constraint::new(-sizes[above].x, sizes[under].x),
    )
}

///////////////////////////////////////////////////////////////////////////////

/// Compute input matrices for an [`osqp`] problem and initialize it.
fn create_qp_problem(
    problem: &QpProblemState,
    sizes: &[Vec2di],
    settings: &osqp::Settings,
) -> Result<osqp::Problem, osqp::SetupError> {
    let n_var = problem.nb_variables();
    let n_coord = problem.coordinate_definitions.len();
    assert_eq!(n_coord, sizes.len());
    // criteria = sum(distance_of_output_center_to_barycenter^2), with barycenter of centers using output area as weights.
    // base coordinates = (x_i, y_i). sizes = (sx_i, syi). weights a_i = sx_i * sy_i.
    // using centers c_i = (x_i + sx_i / 2, y_i + sy_i / 2), barycenter : (sum_i a_i) b = sum_i a_i c_i.
    // min obj = sum_i dist(c_i, b)^2 <=> sum_i | sum_j a_j (c_i - c_j) |^2 = sum_i V_i (for short)
    // V_i = (sum_j a_j (x_i + sx_i/2 - x_j - sx_j/2))^2 + (sum_j a_j (y_i + sy_i/2 - y_j - sy_j/2))^2
    // Looking only at x (mirror of y) : sum_j a_j (x_i + sx_i/2 - x_j - sx_j/2 = X^T * [C:1d array] + c: constant.
    // Thus (sum_j a_j (x_i + sx_i/2 - x_j - sx_j/2))^2 = (X^T C + c)^2 = X^T (C C^T) X + 2 c C^T X + c^2.
    // For minimized objective in osqp, p += C C^T, q += c C, and c^2 is ignored.
    let mut p = RowMatrix::square(n_var, 0.);
    let mut q = vec![0.; n_var];
    for i in 0..n_coord {
        let size_i = &sizes[i];
        let coord_i = &problem.coordinate_definitions[i];
        let mut c_array_x = vec![0.; n_var];
        let mut c_x = 0.;
        let mut c_array_y = vec![0.; n_var];
        let mut c_y = 0.;
        for j in 0..n_coord {
            let size_j = &sizes[j];
            let coord_j = &problem.coordinate_definitions[j];
            let a_j = f64::from(size_j.x) * f64::from(size_j.y);
            accumulate_carray_c(
                &mut c_array_x,
                &mut c_x,
                a_j,
                coord_i.x.clone() + (size_i.x / 2),
                coord_j.x.clone() + (size_j.x / 2),
            );
            accumulate_carray_c(
                &mut c_array_y,
                &mut c_y,
                a_j,
                coord_i.y.clone() + (size_i.y / 2),
                coord_j.y.clone() + (size_j.y / 2),
            )
        }
        p.add_vt_v(&c_array_x);
        add_a_times_array(&mut q, c_x, &c_array_x);
        p.add_vt_v(&c_array_y);
        add_a_times_array(&mut q, c_y, &c_array_y);
    }
    // Constraints : l <= Ax <= u
    let mut a = RowMatrix::empty(n_var);
    let (mut l, mut u) = (Vec::new(), Vec::new());
    for (variable, constraint) in problem.mono_constraints.iter().enumerate() {
        if !constraint.is_unconstrained() {
            a.add_row((0..n_var).map(|i| if i == variable { 1. } else { 0. }));
            l.push(f64::from(constraint.min));
            u.push(f64::from(constraint.max))
        }
    }
    for pos in 0..n_var {
        for neg in 0..pos {
            if let Some(constraint) = problem.dual_constraints.get(neg, pos) {
                a.add_row((0..n_var).map(|i| match i {
                    i if i == pos => 1.,
                    i if i == neg => -1.,
                    _ => 0.,
                }));
                l.push(f64::from(constraint.min));
                u.push(f64::from(constraint.max))
            }
        }
    }
    osqp::Problem::new(&p, &q, &a, &l, &u, settings)
}

fn accumulate_carray_c(
    c_array: &mut [f64],
    c: &mut f64,
    a_j: f64,
    pos: Expression,
    neg: Expression,
) {
    if let Some(variable) = pos.variable {
        c_array[variable.index] += a_j;
    }
    if let Some(variable) = neg.variable {
        c_array[variable.index] -= a_j;
    }
    *c += a_j * f64::from(pos.constant - neg.constant);
}

fn add_a_times_array(acc: &mut [f64], a: f64, array: &[f64]) {
    assert_eq!(acc.len(), array.len());
    for i in 0..acc.len() {
        acc[i] += a * array[i]
    }
}

#[derive(Debug, Clone)]
/// Row-major ordered matrix.
struct RowMatrix<T> {
    nrow: usize,
    ncol: usize,
    array: Vec<T>,
}

impl<T> RowMatrix<T> {
    fn empty(ncol: usize) -> Self {
        Self {
            nrow: 0,
            ncol,
            array: Vec::new(),
        }
    }
    fn square(size: usize, value: T) -> Self
    where
        T: Clone,
    {
        Self {
            nrow: size,
            ncol: size,
            array: vec![value; size * size],
        }
    }
    fn linearized_index(&self, row: usize, col: usize) -> usize {
        assert!(row < self.nrow);
        assert!(col < self.ncol);
        (row * self.ncol) + col
    }
    fn row_major_array<'a>(&'a self) -> &'a [T] {
        &self.array
    }
    fn add_vt_v(&mut self, v: &[T])
    where
        T: Copy + Mul<Output = T> + AddAssign,
    {
        assert_eq!(self.nrow, self.ncol);
        assert_eq!(self.nrow, v.len());
        for row in 0..self.nrow {
            for col in 0..self.ncol {
                let index = self.linearized_index(row, col);
                self.array[index] += v[row] * v[col];
            }
        }
    }
    fn add_row<I: Iterator<Item = T>>(&mut self, iterator: I) {
        self.nrow += 1;
        self.array.extend(iterator.take(self.ncol));
        assert_eq!(self.ncol * self.nrow, self.array.len())
    }
}

impl<'m> From<&'m RowMatrix<f64>> for osqp::CscMatrix<'static> {
    fn from(matrix: &'m RowMatrix<f64>) -> Self {
        osqp::CscMatrix::from_row_iter_dense(
            matrix.nrow,
            matrix.ncol,
            matrix.row_major_array().into_iter().cloned(),
        )
    }
}

///////////////////////////////////////////////////////////////////////////////

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

    // min <= pos - neg <= max
    fn add_dual_constraint(
        &mut self,
        neg: Expression,
        pos: Expression,
        constraint: Constraint,
    ) -> Result<(), Infeasible> {
        match (neg.variable, pos.variable) {
            (None, None) => {
                if !constraint.contains(pos.constant - neg.constant) {
                    return Err(Infeasible);
                }
            }
            (None, Some(pos_var)) => {
                // min <= pos_var + pos_cst - neg_cst <= max
                self.mono_constraints[pos_var.index] = Constraint::merge(
                    &self.mono_constraints[pos_var.index],
                    &constraint.add(neg.constant - pos.constant),
                )?;
            }
            (Some(neg_var), None) => {
                // min <= pos_cst - neg_cst - neg_var <= max
                // -max + pos_cst - neg_cst <= neg_var <= -min + pos_cst - neg_cst
                self.mono_constraints[neg_var.index] = Constraint::merge(
                    &self.mono_constraints[neg_var.index],
                    &constraint.inverse().add(pos.constant - neg.constant),
                )?;
            }
            (Some(neg_var), Some(pos_var)) => {
                // min <= pos_cst + pos_var - neg_cst - neg_var <= max
                let constraint = constraint.add(neg.constant - pos.constant);
                let merged = match self.dual_constraints.get(neg_var.index, pos_var.index) {
                    None => constraint,
                    Some(old_constraint) => Constraint::merge(&constraint, &old_constraint)?,
                };
                self.dual_constraints
                    .set(neg_var.index, pos_var.index, Some(merged));
            }
        }
        Ok(())
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
        // convert dual constraints
        for pos_var in 0..self.nb_variables() {
            if let Some(constraint) = self.dual_constraints.get(variable.index, pos_var) {
                // min <= pos_var - variable <= max
                self.mono_constraints[pos_var] =
                    Constraint::merge(&self.mono_constraints[pos_var], &constraint.add(constant))?
            }
        }
        self.dual_constraints.remove_element(variable.index);
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
        // Update mono constraints
        self.mono_constraints[kept.index] = Constraint::merge(
            &self.mono_constraints[kept.index],
            &self.mono_constraints[removed.index].add(-kept_offset),
        )?;
        // multi constraints : check infeasability of (kept, removed), convert (removed -> kept, x), then remove
        if let Some(constraint) = self.dual_constraints.get(kept.index, removed.index) {
            // min <= removed - kept <= max, with removed = kept + kept_offset
            if !constraint.contains(kept_offset) {
                return Err(Infeasible);
            }
            self.dual_constraints.set(kept.index, removed.index, None)
        }
        for pos_var in 0..self.nb_variables() {
            // min <= pos_var - removed <= max, with removed = kept + kept_offsey
            if let Some(constraint) = self.dual_constraints.get(removed.index, pos_var) {
                // min <= pos_var - kept <= max
                let kept_constraint = constraint.add(kept_offset);
                let merged = match self.dual_constraints.get(kept.index, pos_var) {
                    None => kept_constraint,
                    Some(old_constraint) => Constraint::merge(&kept_constraint, &old_constraint)?,
                };
                self.dual_constraints.set(kept.index, pos_var, Some(merged))
            }
        }
        self.dual_constraints.remove_element(removed.index);
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
    fn evaluate(&self, variables: &[f64]) -> Result<i32, Infeasible> {
        let variable = match self.variable {
            None => 0,
            Some(v) => {
                let float = variables[v.index].round();
                if !(f64::from(i32::MIN)..=f64::from(i32::MAX)).contains(&float) {
                    return Err(Infeasible);
                }
                float as i32
            }
        };
        Ok(self.constant + variable)
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
    let add_constraint = problem.add_dual_constraint(
        problem.coordinate_definitions[0].x.clone(),
        problem.coordinate_definitions[0].y.clone(),
        Constraint::new(-100, 100),
    );
    assert!(add_constraint.is_ok());
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

    assert_eq!(problem.nb_variables(), problem.dual_constraints.size());
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
    let result = problem.add_dual_constraint(
        problem.coordinate_definitions[0].x.clone(), // index 0
        problem.coordinate_definitions[2].y.clone(), // index 4
        Constraint::new(0, 100),
    );
    assert!(result.is_ok());
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
    assert_eq!(
        problem.dual_constraints.get(0, 3),
        Some(Constraint::new(50, 150))
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
    assert!(result.is_err());

    assert_eq!(problem.nb_variables(), problem.dual_constraints.size())
}
