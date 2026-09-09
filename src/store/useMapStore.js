import { create } from 'zustand';

export const useMapStore = create((set) => ({
  inundation: null,
  riskZones: null,
  cloudburstVectors: null,
  logisticsNodes: null,
  
  setLayerData: (layerName, data) => set({ [layerName]: data }),
}));