use std::ops::{Add, Div};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Direction {
    LeftOf,
    RightOf,
    Above,
    Under,
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Vec2d {
    pub x: isize,
    pub y: isize,
}

impl From<(isize, isize)> for Vec2d {
    fn from(pair: (isize, isize)) -> Vec2d {
        let (x, y) = pair;
        Vec2d { x, y }
    }
}

impl Add for Vec2d {
    type Output = Vec2d;
    fn add(self, rhs: Vec2d) -> Vec2d {
        Vec2d {
            x: self.x + rhs.x,
            y: self.y + rhs.y,
        }
    }
}

impl Div<isize> for Vec2d {
    type Output = Vec2d;
    fn div(self, d: isize) -> Vec2d {
        Vec2d {
            x: self.x / d,
            y: self.y / d,
        }
    }
}

/// `x` axis is from left to right. `y` axis is from bottom to top.
/// The rectangle covers pixels in `[bl.x, bl.x+size.x[ X [bl.y, bl.y+size.y[`.
/// Top and right sides are excluded.
pub struct Rect {
    pub bottom_left: Vec2d,
    pub size: Vec2d,
}

impl Rect {
    fn top_right(&self) -> Vec2d {
        self.bottom_left + self.size
    }
    fn bottom_right(&self) -> Vec2d {
        self.bottom_left + Vec2d::from((self.size.x, 0))
    }
    fn top_left(&self) -> Vec2d {
        self.bottom_left + Vec2d::from((0, self.size.y))
    }

    fn center_bottom(&self) -> Vec2d {
        self.bottom_left + Vec2d::from((self.size.x / 2, 0))
    }
    fn center_top(&self) -> Vec2d {
        self.bottom_left + Vec2d::from((self.size.x / 2, self.size.y))
    }
    fn center_left(&self) -> Vec2d {
        self.bottom_left + Vec2d::from((0, self.size.y / 2))
    }
    fn center_right(&self) -> Vec2d {
        self.bottom_left + Vec2d::from((self.size.x, self.size.y / 2))
    }
}

/// Determine if `lhs` is adjacent to `rhs`, and in which direction (`lhs direction rhs`).
/// Current criterion : adjacent
pub fn get_adjacent_direction(lhs: &Rect, rhs: &Rect) -> Option<Direction> {
    let size_average = (lhs.size + rhs.size) / 2;
    let is_adjacent_x = |l: Vec2d, r: Vec2d| l.x == r.x && (l.y - r.y).abs() <= size_average.y;
    let is_adjacent_y = |l: Vec2d, r: Vec2d| l.y == r.y && (l.x - r.x).abs() <= size_average.x;
    if is_adjacent_x(lhs.center_right(), rhs.center_left()) {
        return Some(Direction::LeftOf);
    }
    if is_adjacent_x(lhs.center_left(), rhs.center_right()) {
        return Some(Direction::RightOf);
    }
    if is_adjacent_y(lhs.center_top(), rhs.center_bottom()) {
        return Some(Direction::Under);
    }
    if is_adjacent_y(lhs.center_bottom(), rhs.center_top()) {
        return Some(Direction::Above);
    }
    None
}

#[cfg(test)]
#[test]
fn test_direction() {
    let size = Vec2d::from((1920, 1080));
    let primary = Rect {
        bottom_left: Vec2d::from((0, 0)),
        size,
    };
    let at_right = Rect {
        bottom_left: primary.bottom_right(),
        size,
    };
    let right_overlap = Rect {
        bottom_left: primary.bottom_right() + Vec2d::from((1, 0)),
        size,
    };
    let above_middle = Rect {
        bottom_left: primary.center_top(),
        size,
    };
    let smaller_below = Rect {
        bottom_left: primary.center_bottom() + Vec2d::from((200, -480)),
        size: Vec2d::from((640, 480)),
    };
    assert_eq!(get_adjacent_direction(&primary, &primary), None);
    assert_eq!(
        get_adjacent_direction(&primary, &at_right),
        Some(Direction::LeftOf)
    );
    assert_eq!(
        get_adjacent_direction(&at_right, &primary),
        Some(Direction::RightOf)
    );
    assert_eq!(get_adjacent_direction(&primary, &right_overlap), None);
    assert_eq!(
        get_adjacent_direction(&primary, &above_middle),
        Some(Direction::Under)
    );
    assert_eq!(
        get_adjacent_direction(&at_right, &above_middle),
        Some(Direction::Under)
    );
    assert_eq!(
        get_adjacent_direction(&primary, &smaller_below),
        Some(Direction::Above)
    );
    assert_eq!(get_adjacent_direction(&at_right, &smaller_below), None);
}
