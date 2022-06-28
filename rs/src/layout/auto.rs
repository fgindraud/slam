impl Layout {
    pub fn compute_base_coords(&self, enabled_output_preferred_modes: &[Mode]) -> Vec<Vec2di> {
        assert_eq!(
            enabled_output_preferred_modes.len(),
            self.enabled_outputs.len()
        );
        let output_sizes = Vec::from_iter(
            Iterator::zip(
                self.enabled_outputs.iter(),
                enabled_output_preferred_modes.iter(),
            )
            .map(|(output, preferred_mode)| output.transformed_size(preferred_mode)),
        );
        // TODO handle failure
        // overlap -> add relations
        // failure -> remove relations ?
        compute_rects::compute_optimized_bottom_left_coords(&output_sizes, &self.relations).unwrap()
    }
}

/// Compute rects optimization problem code (lengthy).
mod compute_rects;
