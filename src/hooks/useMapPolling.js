import { useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';
import { useMapStore } from '../store/useMapStore';

export function useMapPolling() {
  const setLayerData = useMapStore((state) => state.setLayerData);

  const { data: riskData } = useQuery({
    queryKey: ['riskZones'],
    queryFn: async () => {
      // Dummy GeoJSON data for map testing
      return {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            properties: { risk_score: 80 }, // Red zone
            geometry: {
              type: "Polygon",
              coordinates: [[[79.2, 30.2], [79.4, 30.2], [79.3, 30.4], [79.2, 30.2]]]
            }
          }
        ]
      };
    },
    refetchInterval: 30000,
  });

  useEffect(() => {
    if (riskData) {
      setLayerData('riskZones', riskData);
    }
  }, [riskData, setLayerData]);
}