from typing import Union, Optional, Dict, Any, Tuple
from gpiozero import DigitalOutputDevice
from RPLCD.i2c import CharLCD
from libcamera import Transform
import utility.config as config
from utility.logger import logger
import adafruit_mlx90614
import adafruit_tcs34725
import adafruit_ltr390
import adafruit_ens160
import adafruit_ahtx0
from busio import I2C
import picamera2
import datetime
import inspect
import asyncio
import time
import sys
import os


def find_median_data(data_list) -> Union[int, float, tuple, None]:
	if data_list:
		if len(data_list) == config.NUM_READINGS:
			data_list.sort()
			return data_list[int(len(data_list)/2)]
	return None
	
class Controller(object):
	"""
		Controller handles sensor object creation, management, and data collection
	"""
	
	STAGGER_INTERVAL = 20 # in minutes
	
	def __init__(self,
				 sensor_pin_map: dict,
				 i2c_bus: I2C,
				 i2c_lock: asyncio.Lock,
				 store_locally: bool=config.STORE_LOCAL,
				 store_drive: bool=config.STORE_DRIVE,
				 database=None,
				 drive_writer=None,
				 local_writer=None ) -> None:
		self.__sensor_list = sensor_pin_map.keys()
		self.__power_pin_map = self._create_power_pins(sensor_pin_map)
		self.__i2c_bus = i2c_bus
		self.__i2c_lock = i2c_lock
		self.__store_locally = store_locally
		self.__store_drive = store_drive
		self.__database = database
		self.__GSWriter = drive_writer
		self.__XLSXWriter = local_writer
		self.__object_map = self._create_object_map()
		self.__current_objects = self._create_objects()
		self.__last_data = None
		
	def _create_power_pins(self, power_pin_map: dict) -> dict:
		"""
			Method for creating GPIO sensor power pins and turning them on
				*args -> str sensor name : int GPIO pin number
		"""
		for sensor, pin in power_pin_map.items():
			if pin is None:
				continue
			
			power_ctrl = DigitalOutputDevice(pin=pin, active_high=True, initial_value=True)
			power_pin_map[sensor] = power_ctrl
			time.sleep(0.2)
		return power_pin_map
		
	def _create_object_map(self) -> dict:
		"""
			Method for generating str -> class map
		"""
		logger.info("Mapping existing classes...")
		object_map = {}
		
		for name, obj in inspect.getmembers(sys.modules[__name__]):
			if inspect.isclass(obj):
				object_map[name] = obj
		logger.info("Mapping complete.")
		
		return object_map
		
	def _create_objects(self) -> list:
		"""
			Method for creating objects based on passed dict of sensors
		"""
		logger.info("Generating objects...")
		objects = []
		
		for name in self.__sensor_list:
			if name in self.__object_map:
				try:
					object_class = self.__object_map[name]
					if name == "Camera":
						obj = object_class()
					else:
						obj = object_class(self.__i2c_bus)
					objects.append(obj)
				except RuntimeError as runtime_error:
					logger.error(f"Error: {runtime_error} when creating object {name}.")
		logger.info("Generation complete.")
		return objects
		
	async def _gather_sensor_data(self) -> None:
		"""
			Method for collecting all sensor object data
		"""
		aht21_exists = co2_exists = False
		
		for sensor in self.__current_objects:
			if isinstance(sensor, TEMP_AHT21):
				aht21_exists = True
				aht21_index = self.__current_objects.index(sensor)
			if isinstance(sensor, CO2_ENS160):
				co2_exists = True
				co2_index = self.__current_objects.index(sensor)
			if isinstance(sensor, Camera):
				full_image_path = await sensor.capture_image()
				if config.STORE_LOCAL and config.SCP_COPY:
					await self._ssh_copy_to_hub(full_image_path)
	
		if aht21_exists and co2_exists:
			if co2_index < aht21_index:
				self.__current_objects.append(self.__current_objects.pop(co2_index))
	
		for _ in range(config.NUM_READINGS):
			for sensor in self.__current_objects:

				if isinstance(sensor, Camera):
					continue
				elif isinstance(sensor, TEMP_AHT21):
					if co2_exists:
						await sensor.collect_data_for_median()
						aht21_temperature = await sensor.get_temperature()
						aht21_humidity = await sensor.get_humidity()
					else:
						await sensor.collect_data_for_median()
				elif isinstance(sensor, CO2_ENS160):
					if aht21_exists:
						sensor.temperature_compensation = aht21_temperature
						sensor.humidity_compensation = aht21_humidity
						await sensor.collect_data_for_median()
					else:
						await sensor.collect_data_for_median()
				else:
					await sensor.collect_data_for_median()
			time.sleep(config.TIME_BETWEEN_READINGS)
			
	async def get_data(self) -> None:
		while True:
			async with self.__i2c_lock:
				logger.info("Collecting data...")
				await self._gather_sensor_data()
				
				sensor_data: Dict[str, Dict[str, Any]] = {}
				for sensor in self.__current_objects:
					if isinstance(sensor, Camera):
						continue
					data = await sensor.package()
					if data is not None:
						sensor_data.update(data)
						sensor.reset_sensor_data()
				logger.info("Collection complete.")
				logger.info(f"Collected at: {datetime.datetime.now().strftime('%m-%d-%Y@%H:%M:%S')}")
				self.__last_data = sensor_data
				next_reading = await self._calc_next_reading()
				
				# code for transmitting
			
			await asyncio.sleep(next_reading)
			
	async def _ssh_copy_to_hub(self, image_path: str) -> None:
		"""
			Optional method for copying images to Pi 4 using SSH/SCP
				*args -> str image path
		"""
		logger.info("Copying image to hub...")
		
		if os.path.exists(image_path):
			copy_command = f"scp {image_path} {config.USERNAME}@{config.IP_ADDRESS}:{config.DESTINATION_COPY_PATH}"
			os.system(copy_command)
			
			# Remove image from local directory if not wanting to store locally (saves storage space)
			if not self.__store_locally:
				del_command = f"rm {image_path}"
				os.system(del_command)
				
	async def _write_to_file(self, data: dict) -> None:
		"""
			Optional method for storing data locally or writing to Google Sheet
				*args -> dict sensor data
		"""
		if self.__store_locally and self.__XLSXWriter:
			await self.__XSLXWriter.write_sensor_data(data)
		if self.__store_drive and self.__GSWriter:
			await self.__GSWriter.write_sensor_data(data)
			
	async def _calc_next_reading(self) -> int:
		"""
			Method for calculating how long to wait until next readings
		"""
		logger.info("Calculating next reading...")
		
		current_time = datetime.datetime.now()
		minutes_next = Controller.STAGGER_INTERVAL - int(current_time.minute % Controller.STAGGER_INTERVAL)
		next_reading = (minutes_next * 60) + current_time.second
		
		return next_reading
		
	async def get_last_data(self) -> Union[dict, None]:
		return self.__last_data
		
class Client(object):
	
	CLIENT_TIMEOUT = 10 # in seconds
	
	def __init__( self, host: str=config.SERVER_IP_ADDRESS, port: int=config.SERVER_PORT ) -> None:
		self.__host = host
		self.__port = port
		
	async def package_data(self, data) -> bytes:
		packaged_data = json.dumps(data).encode("utf-8")
		return packaged_data
		
	async def transmit(self, data) -> None:
		packaged_data = await self.package_data(data)
		try:
			with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
				sock.connect((self.__host, self.__port))
				sock.settimeout(Client.CLIENT_TIMEOUT)
				sock.sendall(packaged_data)
		except socket.timeout:
			logger.exception("Connection timedout")
		
class Camera(picamera2.Picamera2):
	"""
		Camera handles all image/video creation
	"""
	# Set log level to error to remove unneccessary data from logs
	picamera2.Picamera2.set_logging(picamera2.Picamera2.ERROR)
	
	def __init__(self,
				 dimensions: tuple=config.IMAGE_DIMENSIONS,
				 file_format: str=config.IMAGE_FORMAT,
				 use_timestamp: bool=config.USE_TIMESTAMP_AS_NAME ) -> None:
		super().__init__()
		self.__dimensions = dimensions
		self.__file_format = file_format
		self.__use_timestamp = use_timestamp
		
	@property
	def _image_name(self) -> str:
		"""
			Property method for generating image names
		"""
		if self.__use_timestamp:
			return datetime.datetime.now().strftime("%m-%d-%Y@%H:%M:%S")
		return "test1"
		
	async def capture_image(self) -> Union[str, None]:
		"""
			Method for capturing image and returning absolute path to that image
		"""
		try:
			logger.info("Capturing image...")
			configuration = self.create_still_configuration(
				main={"size": self.__dimensions},
				transform=Transform(vflip=1, hflip=1),
				raw=self.sensor_modes[3]
			)
			
			self.configure(configuration)
			self.start(show_preview=False)
			
			await asyncio.sleep(2.0)
			
			full_image_path = config.IMAGE_STORE_PATH+self._image_name+f".{self.__file_format}"
			self.capture_file(
				file_output=full_image_path,
				name="main",
				format=self.__file_format,
				wait=True
			)
			
			self.stop()
			logger.info("Image successfully captured.")
			return full_image_path
		except RuntimeError as runtime_error:
			logger.error(f"Error: {runtime_error} while trying to capture image.")
			return None
			
class LCD(CharLCD):
	def __init__(self, i2c_lock: asyncio.Lock, controller: Controller=None ) -> None:
		super().__init__(
			i2c_expander="PCF8574",
			address=0x27,
			port=1,
			cols=20,
			rows=4,
			dotsize=8,
			auto_linebreaks=True,
			backlight_enabled=True)
		self.__sensor_log = controller
		self.__i2c_lock = i2c_lock
		self.__last_data = None
		
	async def monitor(self) -> None:
		"""
			Method for displaying information on LCD display
		"""
		while True:
			async with self.__i2c_lock:
				await self._write_to_screen()
			await asyncio.sleep(1.0)
					
	async def _display_sensor_data(self, sensor: str, data: dict) -> None:
		"""
			Method for cycling data on screen
				sensor --> str sensor name
				data --> dict sensor data
		"""
		self.clear()
		
		column = (20 - len(sensor)) // 2
		self.cursor_pos = (0, column)
		self.write_string(sensor)
		
		row = 1
		for reading in data:
			if reading == "Node":
				continue
				
			self.cursor_pos = (row, 0)
			if isinstance(data[reading], (tuple, int)):
				self.write_string(f"{reading[:8]} : {data[reading]}")
			else:
				self.write_string(f"{reading[:8]} : {data[reading]:.2f}")
				
			row += 1
			if row == 4:
				await asyncio.sleep(config.LCD_DISPLAY_TIME)
				row = 1
				self.clear()
				self.cursor_pos = (0, column)
				self.write_string(sensor)
				
	async def _write_to_screen(self) -> None:
		self.__last_data = await self.__sensor_log.get_last_data()
		
		if self.__last_data is not None:
			# Display sensor data to LCD
			for sensor, data in self.__last_data.items():
				await self._display_sensor_data(sensor, data)
				await asyncio.sleep(config.LCD_DISPLAY_TIME)
				
			# Display estimated time to next read on LCD
			current_time = datetime.datetime.now()
			time_until_next_reading = (20 - (current_time.minute % 20)) * 60 + (60 - current_time.second)
			messages = ("Next Reading", f"in {time_until_next_reading:.2f}", "seconds")
			await self.display_messages(messages)
			
	async def display_messages(self, messages: Union[str, Tuple[str]]) -> None:
		self.clear()
		
		if isinstance(messages, str):
			self.cursor_pos = (0, 0)
			self.write_string(messages)
		elif isinstance(messages, tuple):
			row = 0
			for message in messages:
				self.cursor_pos = (row, (20 - len(message))//2)
				self.write_string(message)
				row += 1
			await asyncio.sleep(config.LCD_DISPLAY_TIME)
		else:
			raise ValueError("Invalid input for messages: got {type(messages)}, expected str or tuple.")
			
class TEMP_AHT21(adafruit_ahtx0.AHTx0):
	def __init__( self, i2c_bus: I2C, address: int = config.AHT21_ADDRESS ) -> None:
		super().__init__(i2c_bus, address)
		self.reset_sensor_data()
		
	def reset_sensor_data(self) -> None:
		self.__AHT_data = {
			"temperature" : [],
			"relative_humidity" : []
		}
		
	async def collect_data_for_median(self) -> None:
		for key in self.__AHT_data.keys():
			self.__AHT_data[key].append(getattr(self, key))
			
	@property
	async def _read(self) -> bool:
		try:
			for key in self.__AHT_data.keys():
				self.__AHT_data[key] = find_median_data(self.__AHT_data[key])
			return True
		except RuntimeError as runtime_error:
			logger.error(f"Error: {runtime_error} when attempting to read TEMP_AHT21.")
			return False
			
	async def package(self) -> Union[dict, None]:
		data = None
		if await self._read:
			self.__AHT_data["Node"] = config.NODE
			data = {"TEMP_AHT21" : self.__AHT_data}
		return data
		
	async def get_temperature(self) -> Union[int, float]:
		temp = self.__AHT_data["temperature"][0]
		return temp if temp else 25
		
	async def get_humidity(self) -> Union[int, float]:
		humidity = self.__AHT_data["relative_humidity"][0]
		return humidity if humidity else 50
		
class CO2_ENS160(adafruit_ens160.ENS160):
	def __init__( self, i2c_bus: I2C, address: int = config.CO2_ADDRESS) -> None:
		super().__init__(i2c_bus, address)
		self.reset_sensor_data()
		self.temperature_compensation = 25
		self.humidity_compensation = 50
		
	def reset_sensor_data(self) -> None:
		self.__CO2_data = {
			"AQI" : [],
			"TVOC" : [],
			"eCO2" : []
		}
		
	async def collect_data_for_median(self) -> None:
		for key in self.__CO2_data.keys():
			for _ in range(config.CO2_ATTEMPTS):
				flag = False
				reading = getattr(self, key)
				if reading == 0:
					time.sleep(config.TIME_BETWEEN_READINGS)
				else:
					self.__CO2_data[key].append(reading)
					flag = True
				if flag:
					break
					
	@property
	async def _read(self) -> bool:
		try:
			for key in self.__CO2_data.keys():
				self.__CO2_data[key] = find_median_data(self.__CO2_data[key])
			return True
		except RuntimeError as runtime_error:
			logger.error(f"Error: {runtime_error} when attempting to read CO2_ENS160.")
			return False
			
	async def package(self) -> Union[dict, None]:
		data = None
		if await self._read and all(self.__CO2_data[key] for key in self.__CO2_data.keys()):
			self.__CO2_data["Node"] = config.NODE
			data = {"CO2_ENS160" : self.__CO2_data}
		return data
		
	
class RGB_TCS34725(adafruit_tcs34725.TCS34725):
	def __init__( self, i2c_bus: I2C, address: int = config.RGB_ADDRESS, led_pin = config.RGB_LED_PIN ) -> None:
		super().__init__(i2c_bus, address)
		self.__RGB_led = DigitalOutputDevice(pin=led_pin, active_high=True, initial_value=False)
		self.__RGB_led.off()
		self.reset_sensor_data()
		
	def reset_sensor_data(self) -> None:
		self.__RGB_data = {
			"color" : [],
			"color_temperature" : [],
			"lux" : [],
			"color_rgb_bytes" : []
		}
		
	async def collect_data_for_median(self) -> None:
		for key in self.__RGB_data.keys():
			self.__RGB_data[key].append(getattr(self, key))
			
	@property
	async def _read(self) -> bool:
		try:
			for key in self.__RGB_data.keys():
				self.__RGB_data[key] = find_median_data(self.__RGB_data[key])
			return True
		except RuntimeError as runtime_error:
			logger.error(f"Error: {runtime_error} when attempting to read RGB_TCS34725.")
			return False
			
	async def package(self) -> Union[dict, None]:
		data = None
		if await self._read:
			self.__RGB_data["Node"] = config.NODE
			data = {"RGB_TCS34725" : self.__RGB_data}
		return data
		
class IR_MLX90614(adafruit_mlx90614.MLX90614):
	def __init__( self, i2c_bus: I2C, address: int = config.MLX_ADDRESS ) -> None:
		super().__init__(i2c_bus, address)
		self.reset_sensor_data()
		
	def reset_sensor_data(self) -> None:
		self.__MLX_data = {
			"ambient_temperature" : [],
			"object_temperature" : []
		}
		
	async def collect_data_for_median(self) -> None:
		for key in self.__MLX_data.keys():
			self.__MLX_data[key].append(getattr(self, key))
			
	@property
	async def _read(self) -> bool:
		try:
			for key in self.__MLX_data.keys():
				self.__MLX_data[key] = find_median_data(self.__MLX_data[key])
			return True
		except RuntimeError as runtime_error:
			logger.error(f"Error: {runtime_error} when attempting to read IR_MLX90614.")
			return False
			
	async def package(self) -> Union[dict, None]:
		data = None
		if await self._read:
			self.__MLX_data["Node"] = config.NODE
			data = {"IR_MLX90614" : self.__MLX_data}
		return data
		
class UV_LTR390(adafruit_ltr390.LTR390):
	def __init__( self, i2c_bus: I2C, address: int = config.LTR_ADDRESS ) -> None:
		super().__init__(i2c_bus, addess)
		self.reset_sensor_data()
		
	def reset_sensor_data(self) -> None:
		self.__LTR_data = {
			"uvi" : [],
			"lux" : [],
			"light" : [],
			"uvs" : []
		}
		
	async def collect_data_for_median(self) -> None:
		for key in self.__LTR_data.keys():
			self.__LTR_data[key].append(getattr(self, key))
			
	@property
	async def _read(self) -> bool:
		try:
			for key in self.__LTR_data.keys():
				self.__LTR_data[key] = find_median_data(self.__LTR_data[key])
			return True
		except RuntimeError as runtime_error:
			logger.error(f"Error: {runtime_error} when attempting to read UV_LTR390.")
			
	async def package(self) -> Union[dict, None]:
		data = None
		if await self._read:
			self.__LTR_data["Node"] = config.NODE
			data = {"UV_LTR390" : self.__LTR_data}
		return data
