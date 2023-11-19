# main.py
from utility.utils import Controller, LCD
from helpers.pisugar_ups import UPS
import asyncio
import busio
import board

async def main():
	i2c_bus = busio.I2C(board.SCL, board.SDA)
	sensor_pin_map = {
		"Camera" : None,
		"RGB_TCS34725": 13,
		"IR_MLX90614" : 6,
		"TEMP_AHT21" : None,
		"CO2_ENS160" : None,
	}
	''' UV_LTR390 : 5 '''
	
	lock = asyncio.Lock()
	
	control = Controller(sensor_pin_map=sensor_pin_map, i2c_bus=i2c_bus, i2c_lock=lock)
	LCD_display = LCD(i2c_lock=lock, controller=control)
	
	task_sensor_data = asyncio.create_task(control.get_data())
	task_lcd_display = asyncio.create_task(LCD_display.monitor())
	
	await asyncio.gather(task_sensor_data, task_lcd_display)


if __name__ == "__main__":
	asyncio.run(main())
