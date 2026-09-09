import { create } from 'zustand';

export const useMapStore = create((set) => ({
  // Screenshot section 1: Char alag data sources
  inundation: null,
  riskZones: null,
  cloudburstVectors: null,
  logisticsNodes: null,
  
  setLayerData: (layerName, data) => set({ [layerName]: data }),
}));