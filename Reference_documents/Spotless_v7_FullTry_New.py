# Spotless V5 - PetEx code - 29Jan2024
# Import Libraries

import os, sys 
#import RPi.GPIO as GPIO
import gpiod
import time
import urllib.request
import urllib
import re
import multiprocessing
import tkinter as tk
import logging
import smtplib
import ssl
from email.message import EmailMessage
import datetime
from PIL import Image, ImageTk
from tkinter import ttk
from tkinter import Label, StringVar, Canvas
import subprocess
import requests
import socket
import smbus

# use this if there is any issue in importing PIL package (to avoid error of Cannot import PIL)
#sudo apt-get install python3-pil python3-pil.imagetk

# Variable Initialization
global qr
global qr_return
global bstatus
global ustat
global status
global extradry
global start_time
global relay_lines

#Initializing pi 5, new method

# Relay Pins
relays = [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27]
GPIO_CHIP = "gpiochip0"
chip = gpiod.Chip(GPIO_CHIP)

# Request GPIO lines
relay_lines = [chip.get_line(pin) for pin in relays]

for line in relay_lines:
    line.request(consumer="relayControl", type=gpiod.LINE_REQ_DIR_OUT)
    line.set_value(0)


# Peristaltic Pump
ppumps = [10,17,27,22,4]
p1, p2, p3, p4, p5 = [chip.get_line(pin) for pin in ppumps]
# RO Solenoids 24V
rosol = [9,11,5,6]
ro1, ro2, ro3, ro4 = [chip.get_line(pin) for pin in rosol]
# Diagraph Pumps
dia_pump = [13,19]
d1, d2 = [chip.get_line(pin) for pin in dia_pump]
# Solenoid Valve
sol_val = [26,21,20,16,12,7,8]
s1, s2, s3, s4, s5, top, bottom = [chip.get_line(pin) for pin in sol_val]
# 220V Solenoid & RGLight
lig_val = [25,24]
s8, rglight = [chip.get_line(pin) for pin in lig_val]
# High Voltage Relays
high_vol = [23,18,14,15]
pump,flushmain,dry,roof = [chip.get_line(pin) for pin in high_vol]

# Extender Board Relays:

green = 1   #GPB1
geyser = 2 #GPB2


#---------------------Activating Extender Board ------------------

# Initialize I2C bus 3
#bus = smbus.SMBus(3)

# MCP23017 I2C Address
#MCP23017_ADDRESS = 0x22

# MCP23017 Registers
#IODIRB = 0x01  # I/O Direction Register for Port B (1 = Input, 0 = Output)
#OLATB = 0x15   # Output Latch Register for Port B (Controls Outputs)
#GPIOB = 0x13   # GPIO Register for Port B

# Set GPB1 and GPB2 as outputs (Clear corresponding bits in IODIRB)
#bus.write_byte_data(MCP23017_ADDRESS, IODIRB, 0b11111001)  # GPB1 and GPB2 as output, others as input

'''
def relay_on(gpio_pin):
    """Turn ON the relay connected to GPB1 or GPB2"""
    current_state = bus.read_byte_data(MCP23017_ADDRESS, GPIOB)
    new_state = current_state | (1 << gpio_pin)  # Set the bit high
    bus.write_byte_data(MCP23017_ADDRESS, OLATB, new_state)

def relay_off(gpio_pin):
    """Turn OFF the relay connected to GPB1 or GPB2"""
    current_state = bus.read_byte_data(MCP23017_ADDRESS, GPIOB)
    new_state = current_state & ~(1 << gpio_pin)  # Clear the bit
    bus.write_byte_data(MCP23017_ADDRESS, OLATB, new_state)

'''
#---------------------LOGGING Details------------------

log_file = 'Logbook_HonerAq_11May.log'

# Check if any handlers are already configured
if len(logging.getLogger().handlers) > 0:
    # Clear existing handlers
    logging.getLogger().handlers.clear()

logging.basicConfig(filename=log_file,level=logging.INFO, format='%(asctime)s - %(levelname)s -%(message)s')

# Function to check if the log file should be reset
def reset_log_file(file_path):
    if os.path.exists(file_path):
        file_creation_time = datetime.datetime.fromtimestamp(os.path.getctime(file_path))
        if (datetime.datetime.now() - file_creation_time).days >= 7:
            # Ensure all log handlers are closed before clearing the file
            for handler in logging.getLogger().handlers:
                handler.close()
            logging.getLogger().handlers.clear()
            
            open(file_path, 'w').close()  # Clear the contents of the file

# Reset log file if it's older than 7 days
reset_log_file(log_file)

#------------------------------------------------------

def control_roof_lights(roof):
    current_time = datetime.now().time()  # Get the current time

    # Define the time range for lights on (5 PM to 5 AM)
    on_time = datetime.strptime("17:00", "%H:%M").time()  # 5 PM
    off_time = datetime.strptime("05:00", "%H:%M").time()  # 5 AM

    if on_time <= current_time or current_time < off_time:
        roof.set_value(True)  # Turn on the lights
        print("Roof lights turned ON")
    else:
        roof.set_value(False)  # Turn off the lights
        print("Roof lights turned OFF")

#------------------------------------------------------

# Check internet

def check_internet(url='http://www.google.com/', timeout=5):
    try:
        response = requests.get(url, timeout=timeout)
        return response.status_code == 200
    except requests.RequestException:
        return False

def check_internet(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error:
        return False

#------------------------------------------------------

#------------------------------------------------------
# Define email sender and receiver

email_sender = 'spotlessbs02@gmail.com'
email_password = 'namk caiq lmpi yeoe'
email_receiver = 'management@petgully.com'

def get_next_session_number():
    try:
        with open("session_number.txt", "r") as file:
            session_number = int(file.read()) + 1
    except FileNotFoundError:
        session_number = 1001

    with open("session_number.txt", "w") as file:
        file.write(str(session_number))

    return session_number

def get_next_session_number_diy():
    try:
        with open("session_number_diy.txt", "r") as file:
            diy_session_number = int(file.read()) + 1
    except FileNotFoundError:
        diy_session_number = 1001

    with open("session_number_diy.txt", "w") as file:
        file.write(str(diy_session_number))

    return diy_session_number

def BathSmallMail():
    
    # Get current timestamp
    current_time = datetime.datetime.now()
    timestamp = current_time.strftime("%Y%m%d%H%M%S")
    session_number = get_next_session_number()
    
    # Set the subject and body of the email
    subject = f'Honer_Bath-SmallPet-BS2_{session_number:03d}_{timestamp}'
    body = """ Bath Session for Small Pet- Activated by ADMIN"""
    
    return subject,body

def BathLargeMail():
    
    # Get current timestamp
    current_time = datetime.datetime.now()
    timestamp = current_time.strftime("%Y%m%d%H%M%S")
    session_number = get_next_session_number()
    
    # Set the subject and body of the email
    subject = f'Honer_Bath-LargePet-BS2_{session_number:03d}_{timestamp}'
    body = """ Bath Session for Large Pet- Activated by ADMIN"""
    
    return subject,body
    

def DIYBathMail():
    
    # Get current timestamp
    current_time = datetime.datetime.now()
    timestamp = current_time.strftime("%Y%m%d%H%M%S")
    diy_session_number = get_next_session_number_diy()
    # Set the subject and body of the email
    subject = f'DIY_Bath-Customer-BS2_{diy_session_number:03d}_{timestamp}_{qr_return}'
    body = """ Bath Session DIY by the Customer """
    
    return subject,body


def disinfectmail():
    
    session_number = get_next_session_number()
    # Get current timestamp
    current_time = datetime.datetime.now()
    timestamp = current_time.strftime("%Y%m%d%H%M%S")

    # Set the subject and body of the email
    subject = f'Honer_Disinfectant-Demo-BS2_{session_number:03d}_{timestamp}'
    body = """ Disinfectant Demo  """
    
    return subject,body

def testmail():
    
    # Get current timestamp
    current_time = datetime.datetime.now()
    timestamp = current_time.strftime("%Y%m%d%H%M%S")

    # Set the subject and body of the email
    subject = f'Testing Code Activated - _{timestamp}'
    body = """ Test Codes are Activated, Please check authorization """
    
    return subject,body


def send_email_now():

    global qr
    global qr_return

    if(bstatus== "small"):
        subject,body=BathSmallMail()
    elif(bstatus=="large"):
        subject,body=BathLargeMail()
    elif(bstatus=="custdiy"):
        subject,body=DIYBathMail()
    elif(bstatus=="onlydisinfectant"):
        subject,body=disinfectmail()	
    else:
        subject,body=testmail()
    
    em = EmailMessage()
    em['From'] = email_sender																				
    em['To'] = email_receiver
    em['Subject'] = subject
    em.set_content(body)

    # Attach file
    #file_path = 'NewCode_Logbook_Spotless.log'
    file_path=log_file

    # Since .log files might not have a recognized MIME type, set it manually
    mime_type = 'text'
    mime_subtype = 'plain'

    with open(file_path, 'rb') as file:
        em.add_attachment(file.read(),
                          maintype=mime_type,
                          subtype=mime_subtype,
                          filename=file_path)


    # Add SSL (layer of security)
    context = ssl.create_default_context()

    # Log in and send the email
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=context) as smtp:
        smtp.login(email_sender, email_password)
        smtp.sendmail(email_sender, email_receiver, em.as_string())

#------------------------------------------------------

#------------------------------------------------------
# Custom Functions:
#------------------------------------------------------
def center_window(width, height, theApp):
    # get screen width and height
    screen_width = m.winfo_screenwidth()
    screen_height = m.winfo_screenheight()

    # calculate position x and y coordinates
    x = (screen_width/2) - (width/2)
    y = (screen_height/2) - (height/2)
    m.geometry('%dx%d+%d+%d' % (width, height, x, y))

def qrcheck(qr):
    global qr_return
    global bstatus
    global status
    global extradry
    
    # Before executing the main code:
    if check_internet():
        
        logging.info("Internet is active. Proceeding with the QR Check..")
        urllib.request.urlcleanup()
        Mlink  = "http://petgully.com/pgapp/pgbs/admin/sr.php?qr="
        pth = Mlink+qr

        try:
            Response = urllib.request.urlopen(pth)
            content = Response.read().decode("utf-8")
            content = re.sub("'","",content)

            key0="&extradry="
            key1="&bstatus="
            key2="&status="
            key3="qr="

            c1 = content.split(key3)
            c2 = c1[1].split(key2)
            qr_return = c2[0]
            c3 = c2[1].split(key1)
            status= c3[0]
            c4 =c3[1].split(key0)
            bstatus=c4[0]
            extradry=c4[1]

            logging.info("QRCHECK function: Customer Details: QR Code : %s , Status: %s, BathStatus: %s, ExtraDry: %s ",qr_return,status,bstatus,extradry)
            logging.info("----------------------------------------------------")

            return(qr_return,status,bstatus,extradry)
        
        except urllib.error.URLError as e:
            logging.error(f"Error fetching data from the URL: {e}")
            return None
        except IndexError:
            logging.error("Error in splitting the content or accessing list indices.")
            return None
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")
            return None

    # Insert the main logic of Spotless_v13_3.py here
    else:
        logging.info("Internet connection is not active. Please check your connection.")
        if qr=="Bath_Small_Session":
            qr_return,status,bstatus,extradry = "Bath_Small_Session","N","small","N"
            return(qr_return,status,bstatus,extradry)
        elif qr=="Bath_Large_Session":
            qr_return,status,bstatus,extradry = "Bath_Large_Session","N","large","N"
            return(qr_return,status,bstatus,extradry)
        elif qr =="Customer_DIY_Bath":
            qr_return,status,bstatus,extradry = "Customer_DIY_Bath","N","custdiy","N"
            return(qr_return,status,bstatus,extradry)
        elif qr=="MedBath_Small_Session":
            qr_return,status,bstatus,extradry = "MedBath_Small_Session","N","medsmall","N"
            return(qr_return,status,bstatus,extradry)
        elif qr=="MedBath_Large_Session":
            qr_return,status,bstatus,extradry = "MedBath_Large_Session","N","medlarge","N"
            return(qr_return,status,bstatus,extradry)
        elif qr=="Testing_only_Water":
            qr_return,status,bstatus,extradry = "Testing_only_Water","N","onlywater","N"
            return(qr_return,status,bstatus,extradry)

        elif qr =="Disinfectant_Bath_Area":
            qr_return,status,bstatus,extradry = "Disinfectant_Bath_Area","N","onlydisinfectant","N"
            return(qr_return,status,bstatus,extradry)
        else:
            logging.info("Wrong Code activated, Internet is down")

         
def verify(event=None):
    global qr_return, status, bstatus, extradry
    logging.info("Verify Function at %s",datetime.datetime.now())
    
    bg_color = "#000000"  # Black background
    neon_blue = "#00FFFF"  # Neon Blue
    neon_pink = "#FF00FF"  # Neon Pink
    font_style = ("Courier", 15, "bold")  # Distinctive font
    

    qr = inp.get()
    qr_return, status, bstatus, extradry = qrcheck(qr)
    dytime = 3000  # Default display time

    qr_mappings =  {
    "Bath_Small_Session": ("**Admin Bath Small Session Activated**", "Small Pet Bath Session - Activated", "small"),
    "Bath_Large_Session": ("**Admin Bath Large Session Activated**", "Large Pet Bath Session - Activated", "large"),
    "MedBath_Small_Session": ("**Admin MedBath Small Session Activated**", "Small Pet MedBath Session - Activated", "medsmall"),
    "MedBath_Large_Session": ("**Admin MedBath Large Session Activated**", "Large Pet MedBath Session - Activated", "medlarge"),
    "Customer_DIY_Bath": ("**Customer DIY Session Activated**", "Customer DIY Session - Activated", "custdiy"),
    "Disinfectant_Bath_Area": ("**Admin AutoFlush and DisInfectant Activated**", "Disinfectant Stage - Activated", "onlydisinfectant"),
    
    "Testing_only_Dryer": ("Testing Only Dryer Function", "Testing in Progress - Dryer", "onlydrying"),
    "Testing_only_Water": ("Testing Only Water Function", "Testing in Progress - Water", "onlywater"),
    "Testing_only_Flush": ("Testing Only Flush Function", "Testing in Progress - Flush", "onlyflush"),
    "Testing_only_Shampoo": ("Testing Only Dryer Function", "Testing in Progress - Dryer", "onlyshampoo"),
    "Testing_all_Relays": ("Testing QuickTest Function", "Testing in Progress - Relays Test", "quicktest")


    }

    if status == "Y":
        message = "QR Scan is Successful"
        os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/1_Welcome.mp3 vlc://quit")
    elif qr in qr_mappings:
        log_msg, display_msg, bstatus = qr_mappings[qr]
        logging.info(log_msg)
        message = display_msg
        os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/1_Welcome.mp3 vlc://quit")


    else:
        message = "QR is not registered, please contact Management"
        logging.info("Scan Failed: " + message)
        # Adjust font_style if necessary for this message
        font_style = ("Courier", 13)
        status="X"
        
        
    # Common label creation and packing
    outp = tk.Label(m, text=message, font=font_style, bg=neon_blue, fg=bg_color, pady=15)
    outp.pack(fill='x', side='bottom')
    m.after(dytime, m.destroy)


def updatestatus(qr_return,ustat):
    try:
        Uplink = "http://petgully.com/pgapp/pgbs/admin/sr_update.php?qr="
        bstat = "&bstatus="
        logging.info("Bstatus Update: Started")
        urlfinal = Uplink + qr_return + bstat + ustat
        response = urllib.request.urlopen(urlfinal)
        response_data = response.read()
        # Process response_data if needed
        response.close()
        logging.info("BStatus Update: Successful")
    except Exception as e:
        logging.error(f"Error in updatestatus function: {str(e)}")

#------------------------------------------------------
# Backbone Functions - that are required in all the other functions

def playmusic():
    #os.system("pkill vlc")
    music = "cvlc /home/spotless/Downloads/V3_Spotless/Mus/8_hours.mp3"
    os.system(music)

def playvideo():
    video = "vlc /home/spotless/Downloads/V3_Spotless/Vids/FrScreen.mp4 -f --loop"
    #video = "omxplayer --loop /home/pi/Videos/Vids/FrScreen.mp4"
    os.system(video)
    
def beep():
    for i in range(6):
        os.system("cvlc /home/spotless/Downloads/V3_Spotless/Mus/Beep.mp3 vlc://quit")
        time.sleep(.5)

def starttimer(cstage):
    start_time = datetime.datetime.now()
    logging.info("** %s : %s",start_time,cstage)
    return start_time

def endtimer(start_time):
    
    end_time=datetime.datetime.now()
    duration=end_time-start_time
    logging.info("Session Duration: %s ",duration)
    
def Allclose():
    # Assuming the pin variables (p1, p2, ..., s8, dry, pump, green, red) are defined globally
    global extradry
    global relay_lines

    for line in relay_lines:
        line.set_value(False)

    # Additional commands
    #os.system("killall vlc")
    #extradry = ""

def Lightson():
    rglight.set_value(1)
    #relay_on(green)
    



def Lightsoff():
    rglight.set_value(0)
    #relay_off(green)

    os.system("cvlc /home/spotless/Downloads/V3_Spotless/Mus/Powerdown.mp3 vlc://quit")
    #os.system("killall vlc")

def TestingRelays(qr_return):
    global relay_lines
    # Turn all relays ON
    for line in relay_lines:
        line.set_value(1)
        time.sleep(3)
        line.set_value(0)
#------------------------------------------------------
# Highly Important
def toggle_pins(pins, state):
    """Helper function to toggle GPIO pins to a specified state."""
    for pin in pins:
        pin.set_value(state)
#------------------------------------------------------
#------------------------------------------------------

#Ready Time

def pumpready(pin,wt):
    pin.set_value(1)
    time.sleep(wt)
    pin.set_value(0)
 
def emptytime(dia,ro,drainval):
    toggle_pins([dia,ro], True)
    time.sleep(drainval)
    toggle_pins([dia,ro], False)

def justshampoo(qr_return):
    priming_sh(12)
    Shampoo(qr_return,60,10)
    os.system("killall vlc")

def justwater(val):
    Water(val)
    os.system("killall vlc")


def priming(mainflow,localgate,mainro, maindp,dpro,fillval,empval):
    # Mainflow is usually s8, which is a 220v solenoid
    # localgate can be s1 or s3, based on shampoo or dis
    # mainro can be ro1 or ro3, which will fill the tank
    toggle_pins([mainflow,localgate,mainro], True)
    time.sleep(fillval)
    toggle_pins([mainflow,localgate,mainro], False)

    # to Prime, we need to exit the water and keep the diaphgram ready
    # dpro is usally ro2 and ro4,  #val is how long     
    toggle_pins([maindp,dpro], True)
    time.sleep(empval)
    toggle_pins([maindp,dpro], False)

def priming_sh(fillval):
    priming(s8,s1,ro1,d1,ro2,fillval,6)

def priming_dt(fillval):
    priming(s8,s3,ro3,d2,ro4,fillval,6)

def Shampoo(qr_return,val,wt):
    curr_act= "Shampoo"
    st = starttimer(curr_act)

    #logging.info("***Shampoo On : %s", datetime.datetime.now())
    
    shmp = multiprocessing.Process(target=pumpready,args=(p1,wt))
    shmp.start()

    os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/3_Shampoo.mp3 vlc://quit")
    os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/3_Shampoo.mp3 vlc://quit")
    beep()
    
    # Turn On certain GPIO pins at the start
    
    toggle_pins([s8, s1, s2, s4, d1, pump], True)
    time.sleep(val)
    beep()
    toggle_pins([s8, s1,s2, s4, d1, pump], False)

    ustat = "S"
    updatestatus(qr_return,ustat)
    #logging.info("***Shampoo Off: %s", datetime.datetime.now())
    endtimer(st)

    
def Water(val):
    curr_act= "Water"
    st = starttimer(curr_act)
    #logging.info("***Water On : %s", datetime.datetime.now())

    toggle_pins([s8,s5,s2,s4,pump], True)
    time.sleep(val)
    beep()
    toggle_pins([s8,s5,s2,s4,pump], False)
    #logging.info("***Water Off  : %s", datetime.datetime.now())
    endtimer(st)

def Conditioner(qr_return,val,wt):
    curr_act= "Conditioner"
    st = starttimer(curr_act)

    cnd = multiprocessing.Process(target=pumpready,args=(p2,wt))
    cnd.start()

    os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/5_Condition.mp3 vlc://quit")
    # Turn On certain GPIO pins at the start

    toggle_pins([s8, s1, s2,s4, d1, pump], True)
    time.sleep(val)
    beep()
    toggle_pins([s8, s1,s2, s4, d1, pump], False)

    ustat = "C"
    updatestatus(qr_return,ustat)
    #logging.info("***Conditioner Off: %s", datetime.datetime.now())
    endtimer(st)

def Mbath(qr_return,val,wt):
    curr_act= "Medicated_Bath"
    st = starttimer(curr_act)

    #logging.info("***Medicated Bath On : %s", datetime.datetime.now())
    
    mbth = multiprocessing.Process(target=pumpready,args=(p4,wt))
    mbth.start()

    os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/5_Condition.mp3 vlc://quit")
    beep()
    
    # Turn On certain GPIO pins at the start
    
    toggle_pins([s8, s1, s2, s4, d1, pump], True)
    time.sleep(val)
    beep()
    toggle_pins([s8, s1,s2, s4, d1, pump], False)

    ustat = "C"
    updatestatus(qr_return,ustat)
    #logging.info("***Medicated Bath Off: %s", datetime.datetime.now())
    endtimer(st)

def massagetime(val):
    curr_act= "Message_Time"
    
    st = starttimer(curr_act)
    logging.info("Massage Time at %s, for %s seconds", datetime.datetime.now(),val)
    os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/Massage.mp3 vlc://quit")
    time.sleep(val)
    
    logging.info("*** Massage Off: %s ***", datetime.datetime.now())
    endtimer(st)

def Dryer(qr_return,val):
    curr_act= "Drying"
    st = starttimer(curr_act)
    #logging.info("***Dryer On : %s", datetime.datetime.now())
    os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/8_Dryer.mp3 vlc://quit")
    os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/8_Dryer.mp3 vlc://quit")
    dmul = 0.5

    dry.set_value(True)  
    time.sleep(val*dmul) 
    dry.set_value(False)  
    
    os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/9_Break.mp3 vlc://quit")
    time.sleep(15)
    endtimer(st)

    dry.set_value(True)  
    time.sleep(val*dmul) 
    beep()
    dry.set_value(False)  
    
    if qr_return=="Testing_only_Dryer":
        os.system("killall vlc")

    ustat="E"
    updatestatus(qr_return,ustat)
    #logging.info("***Dryer Off : %s", datetime.datetime.now())
    endtimer(st)


def Disinfectant(val,wt):
    
    curr_act= "Disinfectant"    
    st = starttimer(curr_act)
    
    diwt = wt*0.8
    #logging.info("***Disinfectant On : %s", datetime.datetime.now())

    disft = multiprocessing.Process(target=pumpready,args=(p4,diwt))
    disft.start()
    
    os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/12_Disinfect.mp3 vlc://quit")
    
    # Turn On certain GPIO pins at the start
    toggle_pins([s8, s3, s4, s2, d2, pump], True)
    time.sleep(val)
    toggle_pins([s8, s3, s4, s2, d2, pump], False)
    toggle_pins([s8, s5, s2, s4, pump], True)
    time.sleep(val)
    beep()
    toggle_pins([s8, s5, s2, s4, pump], False)
    
    #logging.info("***Disinfectant Off : %s", datetime.datetime.now())
    endtimer(st)

def Flush(val):
    curr_act= "Autoflush"
    st = starttimer(curr_act)
    #logging.info("***Flush On: %s", datetime.datetime.now())
    global qr
    global qr_return
    global bstatus
    global status
    global ustat

    #relay_on(flushmain)
    toggle_pins([top, pump,flushmain], True)
    time.sleep(val)  # Pre-Pump for few seconds before the process begins
    toggle_pins([top, pump], False)

    toggle_pins([bottom, pump], True)
    time.sleep(val)  # Pre-Pump for few seconds before the process begins
    toggle_pins([bottom, pump,flushmain], False)

    #relay_off(flushmain)


    os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/13_Thankyou.mp3 vlc://quit")
    os.system("cvlc /home/spotless/Downloads/V3_Spotless/Mus/Powerdown.mp3 vlc://quit")

    qr=""
    qr_return=""
    bstatus=""
    status=""
    ustat=""
    extradry=""
    if qr_return=="Testing_only_Flush":
        os.system("killall vlc")


    logging.info("***Flush Off: %s", datetime.datetime.now())
    endtimer(st)

# ----------------------------- End of Individual User Functions -----------------------------------------------

# ----------------------------- Working Code - Main Functions---------------------------------------------------

#with Stage
def Spotless(qr_return, sval, cval, dval, wval, dryval, fval, wt, stval, msgval, tdry, pr, stage,ctype):
    
    roof.set_value(True)
    primeval = 10
    logging.info("-------------------------------------------------------")
    curr_act= "Spotless Function"
    mst = starttimer(curr_act)
    logging.info("Stage : %s ", stage)
    logging.info("QR: %s,Shamoo: %s,Conditioner: %s,Dis-infect: %s,Water: %s,Dryval: %s,Flush: %s,WaitTime: %s,StageVal: %s,Massageval: %s,Towel: %s,PR: %s,Stage: %s", qr_return, sval, cval, dval, wval, dryval, fval, wt, stval, msgval, tdry, pr, stage)

    start_time = datetime.datetime.now()
    
    #Priming the bottle for 15 seconds
    prm = multiprocessing.Process(target=priming_sh,args=(primeval,))
    prm.start()
    
    #prmdt = multiprocessing.Process(target=priming_dt,args=(primeval,))
    #prmdt.start()


    # ON BOARDING
    for _ in range(2):
        os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/2_Onboard.mp3 vlc://quit")
    time.sleep(2)
    
    if stage <= 1:
        # Shampoo Stage
        Shampoo(qr_return, sval, wt)
        coprm = multiprocessing.Process(target=priming_sh,args=(primeval,))
        coprm.start() 
        massagetime(msgval)

    if stage <= 2:
        beep()# Water 1
        os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/4_Water.mp3 vlc://quit")
        Water(wval)


    if stage <= 3:
  
        time.sleep(5)
        # Conditioner
        if ctype== 100:
            Conditioner(qr_return, cval, wt)
        elif ctype==200:
            Mbath(qr_return,cval,wt)
        
        massagetime(msgval)
        beep()

    if stage <= 4:
        # Water 2
        os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/6_Water.mp3 vlc://quit")
        newwval = 2*wval
        Water(newwval)

    if stage <= 5:
        # Towel Dry
        curr_act= "Towel Dry"
        st = starttimer(curr_act)
        for _ in range(2):
            os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/7_Towel.mp3 vlc://quit")
        time.sleep(tdry)
        endtimer(st)

    if stage <= 6:
        # Dryer
        Dryer(qr_return, dryval)

    # OFF BOARD
    for _ in range(2):
        os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/10_Offboard.mp3 vlc://quit")
        time.sleep(3)

    if pr == 10:
        # Dis-Infectant
        for _ in range(2):
            os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/11_laststep.mp3 vlc://quit")
            os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/12_Disinfect.mp3 vlc://quit")
            time.sleep(stval)
        
        Disinfectant(dval, wt)
                
    empsh = multiprocessing.Process(target=emptytime,args=(d1,ro2,8))
    empsh.start()

    empdt = multiprocessing.Process(target=emptytime,args=(d2,ro4,8))
    empdt.start()

    # Thank you
    os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/13_Thankyou.mp3 vlc://quit")
    
    end_time = datetime.datetime.now()
    duration = end_time - start_time
    logging.info("Session Duration : %s ", duration)
    logging.info("----------------------------------------------------")
    endtimer(mst)
    os.system("killall vlc")
    Lightsoff()
    roof.set_value(False)
    control_roof_lights(roof)
    
def fromDisinfectant(qr_return, sval, cval, dval, wval, dryval, fval, wt, stval, msgval, tdry, pr, stage,ctype):
    curr_act= "From_Disinfectant"
    logging.info(" ** Customer QR Activated from Disinfectant Stage: %s ", qr_return)
    start_time = datetime.datetime.now()
    #Time Check with seconds
    #primeval = 10
    #frdt = multiprocessing.Process(target=priming_dt,args=(primeval,))
    #frdt.start()
    priming_dt(12)
        
    #Dis-Infectant
    Disinfectant(dval,wt)

    empsh = multiprocessing.Process(target=emptytime,args=(d1,ro2,8))
    empsh.start()

    empdt = multiprocessing.Process(target=emptytime,args=(d2,ro4,8))
    empdt.start()

    #Flush
    Flush(fval)


    #Thank you
    os.system("cvlc /home/spotless/Downloads/V3_Spotless/Voiceover/13_Thankyou.mp3 vlc://quit")

    end_time=datetime.datetime.now()
    duration=end_time-start_time
    logging.info("** The Total Duration of the Session for QR %s is : %s ",qr_return,duration)
    os.system("killall vlc")
    Lightsoff()
    

#Allclose()

try:

    ctr = 1
    curr_act= "Script_Loop"
    st = starttimer(curr_act)
    
    while ctr <= 10000: # count should be increased to >1000 once the machine is ready for public use
        #Allclose()
        logging.info("***Entered While Loop: %s", datetime.datetime.now())
        m = tk.Tk()
        m.title("Spotless")
        m.geometry("850x600")  # Increased window size
        bg_color = "#000000"  # Black background
        neon_blue = "#00FFFF"  # Neon Blue
        neon_pink = "#FF00FF"  # Neon Pink
        font_style = ("Courier", 15, "bold")  # Distinctive font
        
        from tkinter import PhotoImage, font as tkfont
        background_image = PhotoImage(file="Login_Screen_2.gif")  # Update this path
        m.configure(bg=bg_color)
        prompt = tk.Label(m, image=background_image, bg=bg_color, fg=neon_blue, font=font_style, pady=0)
        #prompt.pack(fill='x', side='top', padx=0)
        prompt.place(x=0, y=0, relwidth=1, relheight=1)
        
        #def set_focus(event):
        #    inp.focus_set()
        
        # Change fg from neon_pink to bg_color
        inp = tk.Entry(m, fg="#FFFFFF", bg="#FFFFFF", font=font_style, borderwidth=0)
        inp.bind('<Return>', verify)
        #inp.pack(fill='x', side='top', padx=20, pady=10)
        inp.place(x=573,y=238,width=200,height=30)
        m.after(10000,lambda:inp.focus())


        style_button = {"borderwidth": 0, "padx": 5, "pady": 5}
        ok = tk.Button(m,command=verify, **style_button)
        #ok.pack(fill='x', side='top', padx=5, pady=5)
        ok.place(x=573,y=345,width=200,height=1)

        message_label = tk.Label(m, text='', bg=bg_color, fg=neon_pink, font=font_style)
        message_label.pack(fill='x', side='top', padx=10, pady=10)
        m.after(12000,lambda:inp.focus())

        
        center_window(850, 600, m)
        
        # Remove the window title bar
        #m.overrideredirect(True)
        
        m.mainloop()
        time.sleep(4)
                
        if status == "Y":
            curr_act= "YActivated"
            st = starttimer(curr_act)
            logging.info("***Status is Y: %s", datetime.datetime.now())
            
            if check_internet():
                send_email_now()
            Lightson()

            # Start music and video processes
            Mus = multiprocessing.Process(target=playmusic)
            Mus.start()
            process = subprocess.Popen(['python3', 'received_timer.py', bstatus])
            
            
            # Define mapping for bstatus values to function and arguments
            spot_process_map = {
                                #(qr_return, sval, cval, dval, wval, dryval, fval, wt, stval, msgval, tdry, pr, stage) #200 is Medicated Bath
                "R": (Spotless, (qr_return, 120, 120, 60, 70, 480, 60, 5, 10, 10, 30, 10, 1,100)),
                "M": (Spotless, (qr_return, 120, 120, 60, 70, 480, 60, 5, 10, 10, 30, 10, 1,200)),
                "S": (Spotless, (qr_return, 120, 120, 60, 70, 480, 60, 5, 10, 10, 30, 10, 3,100)),
                "C": (Spotless, (qr_return, 120, 120, 60, 70, 480, 60, 5, 10, 10, 30, 10, 5,100)),
                "E": (fromDisinfectant, (qr_return, 120, 120, 60, 70, 480, 60, 5, 10, 10, 30, 10,100))
            }

            if bstatus in spot_process_map:
                func, args = spot_process_map[bstatus]
                logging.info("-----------Stage of Process : %s--------------",bstatus)
                spot = multiprocessing.Process(target=func, args=args)
                spot.start()
                spot.join()

            # Join music and video processes
            Mus.join()
            #Vid.join()

            ctr += 1
            endtimer(st)


        elif status == "N":
            curr_act= "NActivated"
            st = starttimer(curr_act)
            if check_internet():
                send_email_now()
            #logging.info("***Status in N: %s", datetime.datetime.now())
            Lightson()
  
            
            # Start background music and video processes
            Mus = multiprocessing.Process(target=playmusic)
            Mus.start()
            process = subprocess.Popen(['python3', 'received_timer.py', bstatus])
            #Vid = multiprocessing.Process(target=playvideo)
            #Vid.start()
            
            
            # Define a dictionary mapping 'bstatus' values to functions and their arguments
            process_map = {
                "small": (Spotless, (qr_return, 80, 80, 60, 60, 480, 60, 30, 10, 10, 30, 20,1,100)),
                "large": (Spotless, (qr_return, 100, 100, 60, 60, 600, 60, 50, 10, 10, 30, 20,1,100)),
                "custdiy": (Spotless, (qr_return, 100, 100, 60, 60, 600, 60, 12, 10, 10, 30, 10,1,100)),
                "medsmall": (Spotless, (qr_return, 80, 80, 60, 60, 480, 60, 30, 10, 10, 30, 20,1,200)),
                "medlarge": (Spotless, (qr_return, 100, 100, 60, 60, 600, 60, 50, 10, 10, 30, 20,1,200)),
                "onlydisinfectant": (fromDisinfectant, (qr_return, 100, 100, 60, 60, 600, 60, 15, 10, 10, 30, 20,1,200)),

                "quicktest": (TestingRelays, (qr_return,)),
                "onlydrying": (Dryer, (qr_return,300)),
                "onlywater": (justwater, (90,)),
                "onlyflush": (Flush, (60,)),
                "onlyshampoo": (justshampoo, (qr_return,))

                
            }

            # Check if bstatus is in the process_map and start the corresponding process
            if bstatus in process_map:
                func, args = process_map[bstatus]
                print(f" --------{bstatus} ------ ")
                spot = multiprocessing.Process(target=func, args=args)
                spot.start()
                spot.join()

            # Join the music and video processes
            Mus.join()
            #Vid.join()
            ctr = ctr
            endtimer(st)
          
        else:
            logging.info("***Status Failed: %s", datetime.datetime.now())
            ctr=ctr
            time.sleep(3)
            os.system("killall vlc")

        
        

except KeyboardInterrupt:
    print("Human Intervention")
