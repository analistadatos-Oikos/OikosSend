#!/usr/bin/env python3
"""
OikosSend - Bot de WhatsApp para Constructora Oikos
Versión: 1.0.0
"""

import os
import json
import time
import pickle
import logging
import base64
from datetime import datetime
from pathlib import Path

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - OikosSend - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'oikossend_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class OikosSendBot:
    """Bot principal de OikosSend"""
    
    def __init__(self):
        self.tipo = os.environ.get('TIPO_MENSAJE', 'Inicial')
        self.contactos = json.loads(os.environ.get('CONTACTOS_JSON', '[]'))
        self.plantilla = os.environ.get('PLANTILLA', '')
        self.adjunto = os.environ.get('ADJUNTO', '')
        self.spreadsheet_id = os.environ.get('SPREADSHEET_ID', '')
        self.driver = None
        
        logger.info(f"🚀 Inicializando OikosSend - Tipo: {self.tipo}")
        logger.info(f"📊 Contactos a procesar: {len(self.contactos)}")
    
    def personalizar_mensaje(self, contacto):
        """Reemplaza [Nombre] con el nombre real del contacto"""
        try:
            nombre = contacto.get('nombre', 'cliente')
            mensaje = self.plantilla.replace('[Nombre]', nombre)
            
            # También reemplazar otros placeholders si existen
            mensaje = mensaje.replace('[Nombre]', nombre)
            
            # Agregar adjunto si existe
            if self.adjunto:
                mensaje += f"\n\n📎 Brochure: {self.adjunto}"
            
            return mensaje
        except Exception as e:
            logger.error(f"Error personalizando mensaje: {e}")
            return self.plantilla
    
    def iniciar_chrome(self):
        """Configura Chrome en modo headless"""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            chrome_options.add_argument("--remote-debugging-port=9222")
            
            # Cargar sesión guardada si existe
            if Path('session.pkl').exists():
                chrome_options.add_argument("--user-data-dir=/tmp/chrome_profile")
                logger.info("🔄 Se usará perfil guardado")
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Cargar cookies si existen
            if Path('session.pkl').exists():
                self.driver.get("https://web.whatsapp.com")
                with open('session.pkl', 'rb') as f:
                    cookies = pickle.load(f)
                for cookie in cookies:
                    try:
                        self.driver.add_cookie(cookie)
                    except:
                        pass
                logger.info("✅ Cookies cargadas")
                self.driver.refresh()
                time.sleep(5)
            
            logger.info("✅ Chrome iniciado correctamente")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error iniciando Chrome: {e}")
            return False
    
    def enviar_mensaje_individual(self, contacto):
        """Envía un mensaje a un contacto específico"""
        try:
            telefono = str(contacto.get('telefono', '')).replace(' ', '').replace('-', '').replace('+', '')
            nombre = contacto.get('nombre', 'Cliente')
            
            if not telefono:
                logger.warning(f"⚠️ Teléfono vacío para {nombre}")
                return False
            
            mensaje = self.personalizar_mensaje(contacto)
            
            logger.info(f"📨 Enviando a {nombre} ({telefono})")
            
            # Abrir chat de WhatsApp
            url = f"https://web.whatsapp.com/send?phone={telefono}"
            self.driver.get(url)
            time.sleep(5)
            
            # Esperar a que cargue la caja de texto
            wait = WebDriverWait(self.driver, 20)
            caja_texto = wait.until(
                EC.presence_of_element_located((By.XPATH, 
                    '//div[@contenteditable="true"][@data-tab="10"]'))
            )
            
            # Escribir mensaje
            caja_texto.click()
            time.sleep(1)
            
            # Dividir mensaje largo en partes si es necesario
            if len(mensaje) > 500:
                partes = [mensaje[i:i+500] for i in range(0, len(mensaje), 500)]
                for parte in partes:
                    caja_texto.send_keys(parte)
                    time.sleep(1)
            else:
                caja_texto.send_keys(mensaje)
            
            time.sleep(2)
            
            # Hacer clic en enviar
            boton_enviar = self.driver.find_element(
                By.XPATH, '//button[@data-testid="compose-btn-send"]'
            )
            boton_enviar.click()
            
            logger.info(f"✅ Mensaje enviado a {nombre}")
            time.sleep(3)  # Pausa entre mensajes
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error enviando a {contacto.get('nombre', 'desconocido')}: {e}")
            
            # Tomar screenshot del error
            if self.driver:
                self.driver.save_screenshot(f"error_{int(time.time())}.png")
            
            return False
    
    def actualizar_estados(self, resultados):
        """Actualiza los estados en Google Sheets"""
        try:
            # Conectar a Google Sheets
            scope = ["https://spreadsheets.google.com/feeds", 
                    "https://www.googleapis.com/auth/drive"]
            
            with open('credentials.json', 'r') as f:
                creds_dict = json.load(f)
            
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            
            # Abrir la hoja
            sheet = client.open_by_key(self.spreadsheet_id)
            contactos_sheet = sheet.worksheet('📱 Contactos')
            seguimiento_sheet = sheet.worksheet('📊 Seguimiento')
            
            # Obtener todos los datos
            data = contactos_sheet.get_all_values()
            
            # Columna según tipo de mensaje
            columna_estado = 5 if self.tipo == 'Inicial' else 6
            
            for resultado in resultados:
                contacto = resultado['contacto']
                exitoso = resultado['exitoso']
                
                # Buscar fila del contacto
                for i, row in enumerate(data):
                    if i > 0 and len(row) > 1 and row[1] == contacto['nombre']:
                        # Actualizar estado
                        estado = '✅' if exitoso else '❌'
                        contactos_sheet.update_cell(i+1, columna_estado, estado)
                        
                        # Registrar en seguimiento
                        seguimiento_sheet.append_row([
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            contacto['nombre'],
                            self.tipo,
                            '✅ Enviado' if exitoso else '❌ Fallido',
                            f"Tel: {contacto.get('telefono', 'N/A')}"
                        ])
                        break
            
            logger.info("✅ Estados actualizados en Google Sheets")
            
        except Exception as e:
            logger.error(f"❌ Error actualizando sheets: {e}")
    
    def ejecutar(self):
        """Ejecuta el flujo completo del bot"""
        logger.info("=" * 50)
        logger.info("🏗️ OIKOSSEND - INICIANDO PROCESO")
        logger.info("=" * 50)
        
        # Iniciar Chrome
        if not self.iniciar_chrome():
            logger.error("❌ No se pudo iniciar Chrome")
            return False
        
        resultados = []
        exitosos = 0
        fallidos = 0
        
        try:
            for idx, contacto in enumerate(self.contactos):
                logger.info(f"\n📨 [{idx+1}/{len(self.contactos)}] Procesando...")
                
                exitoso = self.enviar_mensaje_individual(contacto)
                
                resultados.append({
                    'contacto': contacto,
                    'exitoso': exitoso
                })
                
                if exitoso:
                    exitosos += 1
                else:
                    fallidos += 1
            
            # Actualizar Google Sheets
            if resultados:
                self.actualizar_estados(resultados)
            
            # Guardar sesión para próxima vez
            if self.driver:
                cookies = self.driver.get_cookies()
                with open('session.pkl', 'wb') as f:
                    pickle.dump(cookies, f)
                logger.info("💾 Sesión guardada para próximos envíos")
            
        except Exception as e:
            logger.error(f"❌ Error en ejecución: {e}")
            
        finally:
            if self.driver:
                self.driver.quit()
        
        # Resumen final
        logger.info("\n" + "=" * 50)
        logger.info("📊 RESUMEN OIKOSSEND")
        logger.info(f"✅ Exitosos: {exitosos}")
        logger.info(f"❌ Fallidos: {fallidos}")
        logger.info("=" * 50)
        
        return exitosos > 0

if __name__ == "__main__":
    bot = OikosSendBot()
    bot.ejecutar()
