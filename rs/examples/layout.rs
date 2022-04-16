#[path = "../src/geometry.rs"]
mod geometry;
#[path = "../src/layout.rs"]
mod layout;

use geometry::*;

fn boundary_rect(rects: &[geometry::Rect]) -> geometry::Rect {
    let bottom_left = Vec2d {
        x: rects.iter().map(|r| r.bottom_left.x).min().unwrap_or(0),
        y: rects.iter().map(|r| r.bottom_left.y).min().unwrap_or(0),
    };
    let top_right = Vec2d {
        x: rects.iter().map(|r| r.top_right().x).max().unwrap_or(0),
        y: rects.iter().map(|r| r.top_right().y).max().unwrap_or(0),
    };
    Rect {
        bottom_left,
        size: top_right - bottom_left,
    }
}

fn draw_layout(png_path: &std::path::Path, rects: &[geometry::Rect]) {
    let boundary = boundary_rect(rects);
    let mut dt = raqote::DrawTarget::new(boundary.size.x, boundary.size.y);
    // TODO print rects (filled with colors from palette), maybe text ?
    dt.write_png(png_path).unwrap()
}

fn main() {
    let origin = Vec2d::default();
    let rects = [Rect {
        bottom_left: origin,
        size: Vec2d::from((1920, 1080)),
    }];
    draw_layout(std::path::Path::new("test.png"), &rects)
}
