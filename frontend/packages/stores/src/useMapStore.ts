import { create } from 'zustand';

interface MapState {
  lng: number;
  lat: number;
  zoom: number;
  pitch: number;
  bearing: number;
  setCamera: (params: Partial<MapState>) => void;
}

export const useMapStore = create<MapState>((set) => ({
  lng: 79.5,
  lat: 30.5,
  zoom: 10,
  pitch: 0,
  bearing: 0,
  setCamera: (params) => set(params),
}));
