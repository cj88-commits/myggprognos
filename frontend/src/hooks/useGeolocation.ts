import { useCallback, useState } from "react";

interface GeolocationState {
  loading: boolean;
  error: string | null;
}

export function useGeolocation(onLocated: (lat: number, lon: number) => void) {
  const [state, setState] = useState<GeolocationState>({ loading: false, error: null });

  const locate = useCallback(() => {
    if (!("geolocation" in navigator)) {
      setState({ loading: false, error: "Geolocation is not supported in this browser." });
      return;
    }
    setState({ loading: true, error: null });
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setState({ loading: false, error: null });
        onLocated(position.coords.latitude, position.coords.longitude);
      },
      (error) => {
        setState({ loading: false, error: error.message || "Could not determine your location." });
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 }
    );
  }, [onLocated]);

  return { locate, ...state };
}
