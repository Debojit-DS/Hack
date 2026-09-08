export interface WardFeature {
  ward_id: number;
  name: string;
  current_risk_score: number | null;
  ward_boundary: GeoJSON.Polygon;
}

export interface SimulationPollResponse {
  task_id: string;
  status: 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILURE';
  result_geojson: GeoJSON.FeatureCollection | null;
}

export interface SafeHaven {
  shelter_id: number;
  name: string;
  type: 'shelter' | 'helipad';
  capacity: number;
  coordinate: [number, number];
}
