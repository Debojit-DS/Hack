import React, { useState } from 'react';

export default function ControlPanel() {
  const [waterLevel, setWaterLevel] = useState(0);

  const handleSimulate = () => {
    // Aage chalkar yahan 'useMutation' API API call aayegi
    alert(`Simulation started with ${waterLevel} mm/hr intensity!`);
  };
  return (
    <div className="absolute top-4 left-4 bg-[rgba(17,24,32,0.65)] backdrop-blur-md p-5 rounded-xl border border-gray-700 w-80 shadow-2xl z-10 text-white">
      <h2 className="font-bold text-lg mb-4 text-blue-400">Tactical Controls</h2>
      
      <div className="flex flex-col gap-2 mb-6">
        <div className="flex justify-between text-sm text-gray-300">
          <span>Water-Rise Simulator:</span>
          <span className="font-mono text-blue-300">{waterLevel} mm/hr</span>
        </div>
        <input 
          type="range" 
          min="0" 
          max="300" 
          value={waterLevel} 
          onChange={(e) => setWaterLevel(e.target.value)}
          className="w-full cursor-pointer accent-blue-500"
        />
      </div>

      <button 
        onClick={handleSimulate}
        className="w-full bg-blue-600 hover:bg-blue-500 font-semibold py-2 rounded-lg transition-colors"
      >
        Run Simulation
      </button>
    </div>
  );
}