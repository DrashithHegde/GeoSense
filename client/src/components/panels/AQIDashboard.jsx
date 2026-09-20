import { useState, useEffect } from 'react';
import { getMumbaiDemoStations, MUMBAI_SYNTHETIC_DEMO_MODE } from "../../constants/cities";

export default function AQIDashboard() {
    const [stations, setStations] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (MUMBAI_SYNTHETIC_DEMO_MODE) {
            setStations(getMumbaiDemoStations());
            setLoading(false);
            return undefined;
        }

        fetchStations();
        const interval = setInterval(fetchStations, 3600000); // Refresh every hour
        return () => clearInterval(interval);
    }, []);

    const fetchStations = async () => {
        try {
            const response = await fetch("/api/aqi/stations");
            if (!response.ok) {
                throw new Error(`AQI request failed with status ${response.status}`);
            }
            const data = await response.json();
            if (Array.isArray(data) && data.length > 0) {
                setStations(data);
            } else {
                setStations(getMumbaiDemoStations());
            }
        } catch (error) {
            console.error('Failed to fetch AQI stations:', error);
            setStations(getMumbaiDemoStations());
        } finally {
            setLoading(false);
        }
    };

    const getAQIColor = (aqi) => {
        if (!aqi) return 'bg-gray-300';
        if (aqi <= 50) return 'bg-green-500';
        if (aqi <= 100) return 'bg-yellow-500';
        if (aqi <= 150) return 'bg-orange-500';
        if (aqi <= 200) return 'bg-red-500';
        return 'bg-purple-700';
    };

    const getAQIText = (aqi) => {
        if (!aqi) return 'No Data';
        if (aqi <= 50) return 'Good';
        if (aqi <= 100) return 'Moderate';
        if (aqi <= 150) return 'Unhealthy for Sensitive';
        if (aqi <= 200) return 'Unhealthy';
        return 'Hazardous';
    };

    return (
        <div className="absolute bottom-20 left-4 w-80 bg-white rounded-xl shadow-xl z-50">
            <div className="p-3 border-b bg-blue-50 rounded-t-xl">
                <h3 className="font-bold flex items-center gap-2">
                    🌬️ Mumbai Air Quality
                    <span className="text-xs text-gray-500">Live Monitor</span>
                </h3>
            </div>

            <div className="max-h-64 overflow-y-auto p-2">
                {loading ? (
                    <div className="p-4 text-center text-gray-500">Loading AQI data...</div>
                ) : (
                    stations.map((station) => (
                        <div key={station.locality_name} className="p-2 border-b last:border-0">
                            <div className="flex justify-between items-center">
                                <div>
                                    <p className="font-medium text-sm">{station.locality_name}</p>
                                    <p className="text-xs text-gray-500">{station.ward}</p>
                                </div>
                                <div className="text-right">
                                    <div className={`px-2 py-1 rounded-full text-xs text-white ${getAQIColor(station.aqi)}`}>
                                        {station.aqi || 'N/A'}
                                    </div>
                                    <p className="text-xs text-gray-500 mt-1">{getAQIText(station.aqi)}</p>
                                </div>
                            </div>
                            {station.pm25 && (
                                <div className="flex gap-3 mt-1 text-xs text-gray-500">
                                    <span>PM2.5: {station.pm25}</span>
                                    {station.pm10 && <span>PM10: {station.pm10}</span>}
                                </div>
                            )}
                        </div>
                    ))
                )}
            </div>

            <div className="p-2 bg-gray-50 rounded-b-xl text-center text-xs text-gray-400">
                Continuous urban environmental intelligence feed
            </div>
        </div>
    );
}
