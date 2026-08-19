from gps_nmea import NMEADecoder


def test_decoder_handles_mixed_constellation_messages():
    decoder = NMEADecoder()

    gga = "$GNGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*59"
    rmc = "$GNRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*74"
    gsa = "$GPGSA,A,3,04,05,09,12,14,18,19,22,27,28,03,15,2.2,1.7,1.3*31"

    status = decoder.update(gga)
    assert status.has_fix is True
    assert status.satellites == 8
    assert status.time_utc == "12:35:19"
    assert status.fix_quality == 1
    assert status.hdop == 0.9
    assert status.altitude == 545.4
    assert status.constellations == {"GN"}
    assert status.constellation_stats["GN"]["satellites"] == 8

    status = decoder.update(rmc)
    assert status.has_fix is True
    assert status.latitude == 48.1173
    assert status.longitude == 11.516666666666667
    assert status.speed_knots == 22.4

    status = decoder.update(gsa)
    assert status.fix_type == 3
    assert status.pdop == 2.2
    assert status.hdop == 1.7
    assert status.vdop == 1.3
    assert status.constellation_stats["GP"]["satellites"] == 12
    assert status.constellations == {"GN", "GP"}


def test_decoder_reads_satellite_summary_from_gsv():
    decoder = NMEADecoder()
    valid_gsv = "$GPGSV,2,1,08,01,12,123,45,02,15,145,43,03,09,156,41,04,08,171,39*7C"

    status = decoder.update(valid_gsv)
    assert status is not None
    assert status.satellites_in_view == 8
    assert status.visible_satellites["GP"][0]["prn"] == 1
    assert status.visible_satellites["GP"][0]["snr"] == 45


def test_decoder_rejects_bad_checksum():
    decoder = NMEADecoder()
    bad = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*00"
    assert decoder.update(bad) is None
