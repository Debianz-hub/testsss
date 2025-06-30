#!/usr/bin/env python3
"""
MSX Bedrock Server Launcher - Codespaces Optimizado
--------------------------------------------------
Versión específicamente diseñada para GitHub Codespaces
"""

import os
import sys
import subprocess
import time
import logging
import zipfile
import signal
import threading
import json
import shutil
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s: %(message)s',
    stream=sys.stdout
)

# Configuración específica para Codespaces
CONFIG = {
    "version": "1.21.44.01",
    "port": 19132,
    "data_dir": "bedrock-data",
    "mirrors": [
        "https://minecraft.azureedge.net/bin-linux/",
        "https://www.minecraft.net/bedrockdedicatedserver/bin-linux/",
    ],
    "cloudflared_url": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    "timeout": 45,
    "max_retries": 5,
    "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

class CodespacesBedrockManager:
    def __init__(self):
        self.server_process = None
        self.tunnel_process = None
        self.running = False
        self.is_codespaces = self.detect_codespaces()
        
    def detect_codespaces(self):
        """Detecta si estamos ejecutando en GitHub Codespaces"""
        return os.getenv('CODESPACES') == 'true' or os.getenv('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN') is not None
        
    def setup_signal_handlers(self):
        """Configura manejadores de señales para cierre limpio"""
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        """Maneja señales de cierre"""
        logging.info("Recibida señal de cierre, deteniendo servicios...")
        self.cleanup()
        sys.exit(0)

    def install_requests_fallback(self):
        """Instala requests con múltiples métodos de respaldo"""
        try:
            import requests
            return requests
        except ImportError:
            logging.warning("requests no disponible, intentando instalación...")
            
        # Método 1: pip install con --user
        try:
            subprocess.run([
                sys.executable, "-m", "pip", "install", "--user", "--no-cache-dir", 
                "--timeout", "60", "requests", "urllib3", "certifi", "charset-normalizer"
            ], check=True, capture_output=True, timeout=120)
            import requests
            logging.info("requests instalado con --user")
            return requests
        except:
            pass
            
        # Método 2: pip install global (para Codespaces)
        try:
            subprocess.run([
                sys.executable, "-m", "pip", "install", "--no-cache-dir",
                "--timeout", "60", "requests"
            ], check=True, capture_output=True, timeout=120)
            import requests
            logging.info("requests instalado globalmente")
            return requests
        except:
            pass
            
        # Método 3: apt-get (si disponible)
        if self.is_codespaces or os.geteuid() == 0:
            try:
                subprocess.run([
                    "sudo", "apt-get", "update", "-qq"
                ], check=True, capture_output=True, timeout=60)
                subprocess.run([
                    "sudo", "apt-get", "install", "-y", "python3-requests"
                ], check=True, capture_output=True, timeout=120)
                import requests
                logging.info("requests instalado via apt-get")
                return requests
            except:
                pass
        
        logging.warning("No se pudo instalar requests, usando urllib como respaldo")
        return None

    def download_with_urllib(self, url, destination):
        """Descarga usando urllib como respaldo"""
        logging.info(f"Descargando con urllib: {url}")
        
        for attempt in range(CONFIG["max_retries"]):
            try:
                req = Request(url, headers={'User-Agent': CONFIG["user_agent"]})
                
                with urlopen(req, timeout=CONFIG["timeout"]) as response:
                    total_size = int(response.headers.get('Content-Length', 0))
                    downloaded = 0
                    
                    with open(destination, 'wb') as f:
                        while True:
                            chunk = response.read(8192)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            if total_size > 0:
                                progress = (downloaded / total_size) * 100
                                print(f"\rProgreso: {progress:.1f}%", end='', flush=True)
                
                print()
                logging.info("Descarga completada con urllib")
                return True
                
            except (URLError, HTTPError, Exception) as e:
                logging.warning(f"Intento {attempt + 1} fallido: {e}")
                if attempt < CONFIG["max_retries"] - 1:
                    time.sleep(2 ** attempt)  # Backoff exponencial
        
        return False

    def download_with_requests(self, requests_module, url, destination):
        """Descarga usando requests"""
        logging.info(f"Descargando con requests: {url}")
        
        for attempt in range(CONFIG["max_retries"]):
            try:
                headers = {'User-Agent': CONFIG["user_agent"]}
                response = requests_module.get(url, stream=True, timeout=CONFIG["timeout"], headers=headers)
                response.raise_for_status()
                
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                with open(destination, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                progress = (downloaded / total_size) * 100
                                print(f"\rProgreso: {progress:.1f}%", end='', flush=True)
                
                print()
                logging.info("Descarga completada con requests")
                return True
                
            except Exception as e:
                logging.warning(f"Intento {attempt + 1} fallido: {e}")
                if attempt < CONFIG["max_retries"] - 1:
                    time.sleep(2 ** attempt)
        
        return False

    def download_file(self, url, destination):
        """Descarga con múltiples métodos de respaldo"""
        requests_module = self.install_requests_fallback()
        
        if requests_module:
            if self.download_with_requests(requests_module, url, destination):
                return True
        
        # Respaldo con urllib
        return self.download_with_urllib(url, destination)

    def setup_environment(self):
        """Configuración inicial del entorno para Codespaces"""
        logging.info("Preparando entorno para Codespaces...")
        
        data_path = Path(CONFIG["data_dir"])
        data_path.mkdir(exist_ok=True)
        
        # Configuraciones específicas para Codespaces
        if self.is_codespaces:
            logging.info("Detectado entorno GitHub Codespaces")
            # Configurar variables de entorno específicas
            os.environ['DEBIAN_FRONTEND'] = 'noninteractive'
            
        # Verificar espacio en disco
        try:
            disk_usage = shutil.disk_usage(data_path)
            free_gb = disk_usage.free / (1024**3)
            logging.info(f"Espacio libre en disco: {free_gb:.1f} GB")
            
            if free_gb < 1.0:
                logging.warning("Poco espacio en disco disponible")
        except:
            pass
        
        # Verificar permisos de escritura
        test_file = data_path / "test_write"
        try:
            test_file.write_text("test")
            test_file.unlink()
            logging.info("Permisos de escritura verificados")
        except Exception as e:
            logging.error(f"Error de permisos: {e}")
            return False
        
        return True

    def install_bedrock_server(self):
        """Instala el servidor Bedrock con mejor manejo de errores"""
        server_path = Path(CONFIG["data_dir"]) / "bedrock_server"
        
        if server_path.exists():
            logging.info("Servidor ya instalado")
            return True
        
        zip_name = f"bedrock-server-{CONFIG['version']}.zip"
        zip_path = Path(CONFIG["data_dir"]) / zip_name
        
        # Intentar descargar desde los mirrors
        for i, mirror in enumerate(CONFIG["mirrors"]):
            url = f"{mirror}{zip_name}"
            logging.info(f"Intentando mirror {i+1}/{len(CONFIG['mirrors'])}: {mirror}")
            
            if self.download_file(url, zip_path):
                break
        else:
            logging.error("Falló la descarga desde todos los mirrors")
            return False
        
        # Verificar que el archivo se descargó correctamente
        if not zip_path.exists() or zip_path.stat().st_size < 1000000:  # Menos de 1MB
            logging.error("Archivo descargado parece corrupto o incompleto")
            return False
        
        # Extraer usando zipfile
        try:
            logging.info("Extrayendo archivos del servidor...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(CONFIG["data_dir"])
            
            # Verificar que se extrajo correctamente
            if not server_path.exists():
                logging.error("El servidor no se extrajo correctamente")
                return False
            
            # Hacer ejecutable
            server_path.chmod(0o755)
            
            # Limpiar archivo zip
            zip_path.unlink()
            
            logging.info("Servidor instalado correctamente")
            return True
            
        except Exception as e:
            logging.error(f"Error al extraer: {e}")
            return False

    def setup_cloudflared(self):
        """Configura Cloudflared para túnel (opcional en Codespaces)"""
        if not self.is_codespaces:
            return self.setup_cloudflared_regular()
        
        # En Codespaces, el port forwarding está disponible automáticamente
        logging.info("Codespaces detectado - usando port forwarding nativo")
        
        # Intentar configurar cloudflared de todas formas si hay token
        token = os.getenv("CLOUDFLARED_TOKEN")
        if token:
            return self.setup_cloudflared_regular()
        
        logging.info("Sin CLOUDFLARED_TOKEN - usando solo port forwarding de Codespaces")
        return True

    def setup_cloudflared_regular(self):
        """Configuración regular de Cloudflared"""
        cloudflared_path = Path(CONFIG["data_dir"]) / "cloudflared"
        
        # Descargar cloudflared si no existe
        if not cloudflared_path.exists():
            logging.info("Descargando Cloudflared...")
            if not self.download_file(CONFIG["cloudflared_url"], cloudflared_path):
                logging.error("Error descargando Cloudflared")
                return False
            cloudflared_path.chmod(0o755)
        
        # Verificar token
        token = os.getenv("CLOUDFLARED_TOKEN")
        if not token:
            logging.warning("CLOUDFLARED_TOKEN no configurado")
            return False
        
        # Iniciar túnel
        try:
            logging.info("Iniciando túnel Cloudflare...")
            self.tunnel_process = subprocess.Popen(
                [str(cloudflared_path), "tunnel", "run", "--token", token],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Esperar un poco para que se establezca el túnel
            time.sleep(10)
            
            if self.tunnel_process.poll() is None:
                logging.info("Túnel Cloudflare iniciado")
                return True
            else:
                logging.error("El túnel Cloudflare falló al iniciar")
                return False
                
        except Exception as e:
            logging.error(f"Error iniciando túnel: {e}")
            return False

    def configure_server(self):
        """Configura server.properties optimizado para Codespaces"""
        config_path = Path(CONFIG["data_dir"]) / "server.properties"
        
        server_config = {
            "server-name": "MSX Bedrock Server (Codespaces)",
            "gamemode": "survival",
            "difficulty": "normal",
            "allow-cheats": "false",
            "max-players": "8",  # Reducido para Codespaces
            "online-mode": "true",
            "allow-list": "false",
            "server-port": str(CONFIG["port"]),
            "server-portv6": str(CONFIG["port"]),
            "level-name": "MSX-World",
            "level-seed": "",
            "default-player-permission-level": "member",
            "texturepack-required": "false",
            "content-log-file-enabled": "true",
            "compression-threshold": "1",
            "server-authoritative-movement": "server-auth-with-rewind",
            "player-movement-score-threshold": "20",
            "player-movement-distance-threshold": "0.3",
            "player-movement-duration-threshold-in-ms": "500",
            "correct-player-movement": "false",
            "server-authoritative-block-breaking": "false",
            "chat-restriction": "None",
            "disable-player-interaction": "false",
            "client-side-chunk-generation-enabled": "true",
        }
        
        logging.info("Configurando servidor para Codespaces...")
        with open(config_path, 'w') as f:
            for key, value in server_config.items():
                f.write(f"{key}={value}\n")

    def get_connection_info(self):
        """Obtiene información de conexión específica para Codespaces"""
        if self.is_codespaces:
            codespace_name = os.getenv('CODESPACE_NAME', 'unknown')
            github_domain = os.getenv('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN', 'preview.app.github.dev')
            
            connection_info = f"{codespace_name}-{CONFIG['port']}.{github_domain}"
            
            return {
                "type": "codespaces",
                "address": connection_info,
                "port": CONFIG['port'],
                "note": "Asegúrate de que el puerto esté configurado como público en Codespaces"
            }
        
        if self.tunnel_process:
            return {
                "type": "cloudflare",
                "address": "Revisa logs de Cloudflare para la URL",
                "port": CONFIG['port'],
                "note": "Túnel Cloudflare activo"
            }
        
        return {
            "type": "local",
            "address": f"localhost:{CONFIG['port']}",
            "port": CONFIG['port'],
            "note": "Conexión local únicamente"
        }

    def start_server(self):
        """Inicia el servidor Bedrock"""
        server_path = Path(CONFIG["data_dir"]) / "bedrock_server"
        
        if not server_path.exists():
            logging.error("Servidor no encontrado")
            return False
        
        os.chdir(CONFIG["data_dir"])
        logging.info("Iniciando servidor Bedrock...")
        
        try:
            self.running = True
            self.server_process = subprocess.Popen(
                ["./bedrock_server"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Mostrar logs en tiempo real
            def log_reader():
                if self.server_process and self.server_process.stdout:
                    for line in iter(self.server_process.stdout.readline, ''):
                        if line and self.running:
                            timestamp = time.strftime("%H:%M:%S")
                            print(f"[{timestamp}] {line.rstrip()}")
            
            log_thread = threading.Thread(target=log_reader, daemon=True)
            log_thread.start()
            
            # Esperar a que termine el proceso
            self.server_process.wait()
            
        except KeyboardInterrupt:
            logging.info("Deteniendo servidor...")
        except Exception as e:
            logging.error(f"Error ejecutando servidor: {e}")
        finally:
            self.running = False

    def cleanup(self):
        """Limpia procesos al cerrar"""
        self.running = False
        
        if self.server_process:
            logging.info("Deteniendo servidor...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                logging.warning("Forzando cierre del servidor...")
                self.server_process.kill()
        
        if self.tunnel_process:
            logging.info("Deteniendo túnel...")
            self.tunnel_process.terminate()
            try:
                self.tunnel_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.tunnel_process.kill()

    def run(self):
        """Ejecuta el launcher completo"""
        print("\n" + "="*70)
        print("🎮 MSX BEDROCK SERVER LAUNCHER - CODESPACES OPTIMIZADO")
        print("="*70)
        
        if self.is_codespaces:
            print("🚀 Ejecutando en GitHub Codespaces")
        
        self.setup_signal_handlers()
        
        if not self.setup_environment():
            sys.exit(1)
        
        if not self.install_bedrock_server():
            logging.error("Error instalando servidor")
            sys.exit(1)
        
        self.configure_server()
        
        # Configurar túnel (opcional)
        tunnel_ok = self.setup_cloudflared()
        if not tunnel_ok:
            logging.info("Continuando sin túnel Cloudflare...")
        
        # Mostrar información de conexión
        connection_info = self.get_connection_info()
        
        print(f"\n🔗 INFORMACIÓN DE CONEXIÓN:")
        print(f"   Tipo: {connection_info['type'].upper()}")
        print(f"   Dirección: {connection_info['address']}")
        print(f"   Puerto: {connection_info['port']}")
        print(f"   Nota: {connection_info['note']}")
        
        if self.is_codespaces:
            print(f"\n📋 INSTRUCCIONES PARA CODESPACES:")
            print(f"   1. Ve a la pestaña 'PORTS' en VS Code")
            print(f"   2. Encuentra el puerto {CONFIG['port']}")
            print(f"   3. Haz clic derecho -> 'Port Visibility' -> 'Public'")
            print(f"   4. Usa la URL mostrada para conectarte")
        
        print(f"\n📝 COMANDOS:")
        print(f"   - Presiona CTRL+C para detener el servidor")
        print(f"   - El servidor guardará automáticamente al cerrar")
        print("\n" + "="*70 + "\n")
        
        # Iniciar servidor
        self.start_server()
        
        # Limpiar al salir
        self.cleanup()

def main():
    """Función principal"""
    try:
        manager = CodespacesBedrockManager()
        manager.run()
    except Exception as e:
        logging.error(f"Error crítico: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
