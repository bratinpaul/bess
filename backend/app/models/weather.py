from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Numeric, Text

from app.database import Base


class WeatherStation(Base):
    """A weather station of a site (battery_master.weather_station)."""

    __tablename__ = "weather_station"
    __table_args__ = {"schema": "battery_master"}

    station_id = Column(BigInteger, primary_key=True)
    site_id = Column(BigInteger, ForeignKey("site.site_id"))
    station_code = Column(Text, nullable=False)
    provider = Column(Text)
    latitude = Column(Numeric)
    longitude = Column(Numeric)


class WeatherActual(Base):
    """Measured weather at a station (5-min): air temperature, global horizontal irradiance, humidity, wind, cloud."""

    __tablename__ = "weather_actual"
    __table_args__ = {"schema": "battery_telemetry"}

    station_id = Column(BigInteger, ForeignKey("battery_master.weather_station.station_id"), primary_key=True)
    ts = Column(DateTime(timezone=True), primary_key=True)
    temp_c = Column(Numeric)
    ghi_wm2 = Column(Numeric)
    humidity_pct = Column(Numeric)
    wind_ms = Column(Numeric)
    cloud_fraction = Column(Numeric)


class WeatherForecast(Base):
    """A weather forecast run: values for each valid hour, from the run issued at issued_at."""

    __tablename__ = "weather_forecast"
    __table_args__ = {"schema": "battery_telemetry"}

    station_id = Column(BigInteger, ForeignKey("battery_master.weather_station.station_id"), primary_key=True)
    issued_at = Column(DateTime(timezone=True), primary_key=True)
    valid_at = Column(DateTime(timezone=True), primary_key=True)
    temp_c = Column(Numeric)
    ghi_wm2 = Column(Numeric)
