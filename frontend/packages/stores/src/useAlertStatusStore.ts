import { create } from 'zustand';

type AlertStatus = 'GREEN' | 'ORANGE' | 'RED';

interface AlertStatusState {
  status: AlertStatus;
  lastUpdated: string;
  setStatus: (status: AlertStatus) => void;
}

export const useAlertStatusStore = create<AlertStatusState>((set) => ({
  status: 'GREEN',
  lastUpdated: new Date().toISOString(),
  setStatus: (status) => set({ status, lastUpdated: new Date().toISOString() }),
}));
