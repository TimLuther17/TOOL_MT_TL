from Bus.Battery_Bus import Battery_Bus
from Bus.LD_Bus_Leistung import LD_Bus
from Bus.Powertrain_Bus_Leistung import Powertrain_Bus


import sys
import os

# Sicherstellen, dass das Hauptprojektverzeichnis im Suchpfad ist
sys.path.append(os.path.abspath(os.path.dirname(__file__) + '/..'))

class Vehicle:
    """Class for all SUMO related and general + plotting variables and methods"""

    '''TO DO: Adding different EMs and Safing EM info in EM. ALSO IMPORTANT TO SET MAX Accel and Speed just für SUMO controller!!!'''

    def __init__(self,veh_setup,veh_num):

        # Fahrzeugattribute
        self.Number = veh_num
        self.Name = veh_setup['Vehicle']
        self.mass = veh_setup['mass']
        self.front_area = veh_setup['front area']
        self.c_w = veh_setup['c_w']
        self.rot_inertia = veh_setup['rot inertia']    #Prinzipiell kann rot inertia bei Schaltgetriebe und Audi vorne hinten variieren
        self.rolling_radius_front = veh_setup['rolling radius front']
        self.rolling_radius_rear = veh_setup['rolling radius rear']
        self.c_rolling = veh_setup['c_rolling']
        self.gear_ratio_front = veh_setup['gear ratio front']
        self.gear_ratio_rear = veh_setup['gear ratio rear']
        self.gear_ratio_rear_1 = veh_setup['gear ratio rear 1']
        self.gear_ratio_rear_2 = veh_setup['gear ratio rear 2']
        self.eta_gear_front = veh_setup['eta gear front']
        self.eta_gear_rear = veh_setup['eta gear rear']
        self.em_front_map_path = veh_setup['EM front Map path']
        self.em_rear_map_path = veh_setup['EM rear Map path']

        self.num_motors = veh_setup.get('num_motors', 2)  # Fallback auf 2 Motoren

        # Batterieattribute
        self.battery_capacity = veh_setup['Batterie Kapazitaet']
        self.battery_eta = veh_setup['Batterie eta']
        self.start_SOC = veh_setup['Batterie Start SOC']

        self.init_Battery(veh_setup)
        self.init_powertrain(veh_setup)


    def init_Battery(self, veh_setup):
            self.Battery = Battery_Bus(veh_setup)


    def init_powertrain(self, veh_setup):
            self.Longitudinal_Dynamics = LD_Bus(self.Name)
            self.EM_front_1 = Powertrain_Bus(self.em_front_map_path, self.eta_gear_front, self.gear_ratio_front)
            self.EM_front_2 = Powertrain_Bus(self.em_front_map_path, self.eta_gear_front, self.gear_ratio_front)
            self.EM_rear_1 = Powertrain_Bus(self.em_rear_map_path, self.eta_gear_rear, self.gear_ratio_rear)
            self.EM_rear_2 = Powertrain_Bus(self.em_rear_map_path, self.eta_gear_rear, self.gear_ratio_rear)
