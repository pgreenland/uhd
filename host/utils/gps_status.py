import uhd
from gps_nmea import monitor_uart


def main():
    # Connect to the USRP device
    usrp = uhd.usrp.MultiUSRP("type=b200")

    # Get the GPSDO UART interface
    uart = usrp.get_gpsdo_uart(0)

    # Set the UART baud rate by performing a write operation
    uart.write_uart_bytes(b"\r\n")

    # Monitor the GPS UART for incoming NMEA sentences
    try:
        monitor_uart(uart)
    except KeyboardInterrupt:
        print("\nGPS UART monitoring stopped.")


if __name__ == "__main__":
    main()
