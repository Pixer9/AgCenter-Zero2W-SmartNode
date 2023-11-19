# pisugar_ups.py
import pisugar
import datetime

""" https://github.com/PiSugar/pisguar-server-py/blob/main/pisugar/pisguar.py """
class UPS(pisugar.PiSugarServer):
	def __init__(self) -> None:
		self.__conn, self.__event_conn = pisugar.connect_tcp('smartnode.local')
		super().__init__(self.__conn, self.__event_conn)
		
	def display_batter_info(self) -> None:
		print(f"Battery Level: {self.get_battery_level()}")
		print(f"Battery Voltage: {self.get_battery_voltage()}")
		print(f"Battery Current: {self.get_battery_current()}")
		print(f"Battery LED: {self.get_battery_led_amount()}")
		print(f"Battery Charging: {self.get_battery_charging()}")
		print(f"Battery Charging Range: {self.get_battery_charging_range()}")
		print(f"Battery Shutdown Level: {self.get_battery_safe_shutdown_level()}")
		
	@property
	def rtc(self) -> datetime.datetime:
		return self.get_rtc_time()
		
	def update_rtc(self) -> None:
		self.rtc_pi2rtc()
		
	def check_update_date_time(self) -> None:
		current_year = datetime.datetime.now().year
		# Need a better check here
		if current_year < 2023:
			self.rtc_rtc2pi()
			
if __name__ == "__main__":
	ups = UPS()
	ups.set_battery_safe_shutdown_level(60)
	ups.display_battery_info()
	print(ups.rtc)
