import React from 'react';
import Map, { Source, Terrain, Layer } from 'react-map-gl/mapbox';
import 'mapbox-gl/dist/mapbox-gl.css';

// Apni banayi hui files ko import kar rahe hain
import { useMapStore } from './store/useMapStore';
import { useMapPolling } from './hooks/useMapPolling';
import ControlPanel from './components/ControlPanel';

export default function App() {
  const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN;
  const riskZones = useMapStore((state) => state.riskZones);
  
  // Background mein data fetch karne wala hook chalu kar diya
  useMapPolling();

  return (
    <div className="w-screen h-screen bg-gray-900 overflow-hidden relative">
      <Map
        initialViewState={{
          longitude: 79.3219, 
          latitude: 30.2730,
          zoom: 10,
          pitch: 55,         
          bearing: -20       
        }}
        mapStyle="mapbox://styles/mapbox/dark-v11"
        mapboxAccessToken={MAPBOX_TOKEN}
      >
        {/* 3D Pahadi Area (Terrain) Load Karega */}
        <Source id="mapbox-dem" type="raster-dem" url="mapbox://mapbox.mapbox-terrain-dem-v1" tileSize={512} maxzoom={14} />
        <Terrain source="mapbox-dem" exaggeration={1.5} />

        {/* Dummy Data se Red Triangle Banayega */}
        {riskZones && (
          <Source id="risk-zones-data" type="geojson" data={riskZones}>
            <Layer
              id="risk-zones-layer"
              type="fill"
              paint={{
                'fill-color': 'red',
                'fill-opacity': 0.4
              }}
            />
          </Source>
        )}
      </Map>

      {/* Glass Panel Map ke upar aayega */}
      <ControlPanel />
    </div>
  );
}