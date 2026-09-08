from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


class DesignInputError(ValueError):
    """Raised when imported or edited model data cannot be designed safely."""


MemberShape = Literal["Rectangular", "Circular"]
ColumnEnd = Literal["I", "J", "Intermediate"]


@dataclass(frozen=True)
class BeamMember:
    member_id: str
    label: str
    story: str
    section_name: str
    material_name: str
    point_i: str
    point_j: str
    i_x_m: float
    i_y_m: float
    i_z_m: float
    j_x_m: float
    j_y_m: float
    j_z_m: float
    width_mm: float
    depth_mm: float
    angle_deg: float = 0.0

    @property
    def length_m(self) -> float:
        dx = self.j_x_m - self.i_x_m
        dy = self.j_y_m - self.i_y_m
        dz = self.j_z_m - self.i_z_m
        return (dx * dx + dy * dy + dz * dz) ** 0.5


@dataclass(frozen=True)
class BeamForce:
    member_id: str
    combination: str
    station_m: float
    step_type: str
    step_num: float
    p_kn: float
    v2_kn: float
    v3_kn: float
    t_knm: float
    m2_knm: float
    m3_knm: float


@dataclass(frozen=True)
class ColumnMember:
    member_id: str
    label: str
    story: str
    section_name: str
    material_name: str
    point_i: str
    point_j: str
    i_x_m: float
    i_y_m: float
    i_z_m: float
    j_x_m: float
    j_y_m: float
    j_z_m: float
    shape: MemberShape
    width_mm: float
    depth_mm: float
    diameter_mm: float = 0.0
    angle_deg: float = 0.0

    @property
    def length_m(self) -> float:
        dx = self.j_x_m - self.i_x_m
        dy = self.j_y_m - self.i_y_m
        dz = self.j_z_m - self.i_z_m
        return (dx * dx + dy * dy + dz * dz) ** 0.5

    @property
    def gross_area_mm2(self) -> float:
        if self.shape == "Circular":
            from math import pi

            return pi * self.diameter_mm**2 / 4.0
        return self.width_mm * self.depth_mm


@dataclass(frozen=True)
class ColumnForce:
    member_id: str
    combination: str
    end: ColumnEnd
    station_m: float
    step_type: str
    step_num: float
    p_kn: float  # Compression is positive in the application data contract.
    v2_kn: float
    v3_kn: float
    t_knm: float
    m2_knm: float
    m3_knm: float


@dataclass(frozen=True)
class DesignSettings:
    concrete_strength_mpa: float = 28.0
    steel_yield_strength_mpa: float = 420.0
    steel_modulus_mpa: float = 200_000.0
    concrete_cover_mm: float = 40.0
    preferred_beam_bar_mm: int = 20
    preferred_column_bar_mm: int = 20
    preferred_stirrup_mm: int = 10
    minimum_beam_bars: int = 2
    minimum_column_ratio: float = 0.01
    maximum_column_ratio: float = 0.06
    beam_phi_flexure_max: float = 0.90
    shear_phi: float = 0.75
    lightweight_factor: float = 1.0
    column_tied_phi_min: float = 0.65
    column_phi_max: float = 0.90
    column_axial_cap_factor: float = 0.80
    column_biaxial_exponent: float = 1.0
    assume_etabs_pdelta: bool = True
    column_effective_length_factor: float = 1.0
    slenderness_warning_limit: float = 22.0
    development_length_factor: float = 40.0
    design_torsion: bool = True


@dataclass(frozen=True)
class RebarSelection:
    count: int
    diameter_mm: int
    layers: int
    area_mm2: float
    required_area_mm2: float
    effective_depth_mm: float
    phi_mn_knm: float
    utilization: float
    tension_strain: float
    fits: bool = True

    @property
    def description(self) -> str:
        suffix = f" ({self.layers} layers)" if self.layers > 1 else ""
        return f"{self.count}Ø{self.diameter_mm}{suffix}"


@dataclass(frozen=True)
class StirrupSelection:
    diameter_mm: int
    legs: int
    spacing_mm: int
    required_av_over_s: float
    provided_av_over_s: float
    shear_capacity_kn: float
    shear_utilization: float
    torsion_capacity_knm: float
    torsion_utilization: float

    @property
    def description(self) -> str:
        return f"{self.legs}-leg Ø{self.diameter_mm} @ {self.spacing_mm}"


@dataclass(frozen=True)
class BeamDesign:
    member: BeamMember
    mark: str
    top_left: RebarSelection
    top_mid: RebarSelection
    top_right: RebarSelection
    bottom_left: RebarSelection
    bottom_mid: RebarSelection
    bottom_right: RebarSelection
    stirrup_left: StirrupSelection
    stirrup_mid: StirrupSelection
    stirrup_right: StirrupSelection
    support_zone_length_m: float
    maximum_flexural_utilization: float
    maximum_shear_utilization: float
    maximum_torsion_utilization: float
    governing_combination: str
    governing_moment_knm: float
    governing_shear_kn: float
    governing_torsion_knm: float
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def status(self) -> str:
        if (
            self.maximum_flexural_utilization > 1.0 + 1e-9
            or self.maximum_shear_utilization > 1.0 + 1e-9
            or self.maximum_torsion_utilization > 1.0 + 1e-9
            or any(not x.fits for x in self.longitudinal_selections)
        ):
            return "FAIL"
        if self.warnings:
            return "WARNING"
        return "OK"

    @property
    def longitudinal_selections(self) -> tuple[RebarSelection, ...]:
        return (
            self.top_left,
            self.top_mid,
            self.top_right,
            self.bottom_left,
            self.bottom_mid,
            self.bottom_right,
        )


@dataclass(frozen=True)
class InteractionPoint:
    axial_kn: float
    moment_knm: float
    nominal_axial_kn: float
    nominal_moment_knm: float
    phi: float
    neutral_axis_mm: float
    tension_strain: float


@dataclass(frozen=True)
class ColumnBarLayout:
    shape: MemberShape
    diameter_mm: int
    coordinates_mm: tuple[tuple[float, float], ...]
    area_mm2: float
    ratio: float
    bars_along_width: int = 0
    bars_along_depth: int = 0

    @property
    def count(self) -> int:
        return len(self.coordinates_mm)

    @property
    def description(self) -> str:
        return f"{self.count}Ø{self.diameter_mm}"


@dataclass(frozen=True)
class ColumnDemandCheck:
    combination: str
    end: ColumnEnd
    axial_kn: float
    m2_knm: float
    m3_knm: float
    m2_capacity_knm: float
    m3_capacity_knm: float
    axial_utilization: float
    m2_utilization: float
    m3_utilization: float
    biaxial_utilization: float


@dataclass(frozen=True)
class ColumnDesign:
    member: ColumnMember
    mark: str
    layout: ColumnBarLayout
    tie_diameter_mm: int
    tie_legs_per_direction: int
    tie_spacing_end_mm: int
    tie_spacing_mid_mm: int
    confinement_length_mm: float
    governing_shear_kn: float
    shear_capacity_kn: float
    maximum_shear_utilization: float
    interaction_m2: tuple[InteractionPoint, ...]
    interaction_m3: tuple[InteractionPoint, ...]
    demand_checks: tuple[ColumnDemandCheck, ...]
    slenderness_m2: float
    slenderness_m3: float
    maximum_axial_utilization: float
    maximum_m2_utilization: float
    maximum_m3_utilization: float
    maximum_biaxial_utilization: float
    governing_combination: str
    governing_end: ColumnEnd
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def status(self) -> str:
        if (
            self.maximum_biaxial_utilization > 1.0 + 1e-9
            or self.maximum_axial_utilization > 1.0 + 1e-9
            or self.maximum_shear_utilization > 1.0 + 1e-9
        ):
            return "FAIL"
        if self.warnings:
            return "WARNING"
        return "OK"


@dataclass(frozen=True)
class ProjectDesign:
    beams: tuple[BeamDesign, ...]
    columns: tuple[ColumnDesign, ...]
    settings: DesignSettings
    import_notes: tuple[str, ...] = field(default_factory=tuple)

    def column_by_id(self, member_id: str | None) -> ColumnDesign:
        if not self.columns:
            raise DesignInputError("No columns are available for the interaction diagram.")
        if member_id:
            for column in self.columns:
                if column.member.member_id == member_id or column.member.label == member_id:
                    return column
        return self.columns[0]
