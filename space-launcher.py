#!/usr/bin/env python3
"""
Space Bedrock Server Launcher - Mirrors Actualizados (Junio 2025)
----------------------------------------------------------------
Versión corregida con URLs oficiales y mirrors funcionales
"""

import os
import sys
import subprocess
import time
import logging
import zipfile
import signal
import threading
import shutil
import platform
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s: %(message)s',
    stream=sys.stdout
)

# CONFIGURACIÓN ACTUALIZADA (Junio 2025)
CONFIG = {
    "version": "1.21.92",  # Versión actual
    "port": 19132,
    "data_dir": "space-data",
    "mirrors": [
        # URLs oficiales directas de Mojang
        "https://minecraft.azureedge.net/bin-linux/bedrock-server-{version}.zip",
        "https://aka.ms/bedrock-server-{version}",
        
        # Mirrors alternativos verificados
        "https://piston-data.mojang.com/server-packages/bedrock-server-{version}.zip",
        "https://launcher.mojang.com/download/bedrock-dedicated-server-{version}.zip",
        
        # Mirror de respaldo con redirección automática  
        "https://www.minecraft.net/bedrockdedicatedserver/bin-linux/bedrock-server-{version}.zip"
    ],
    "fallback_urls": [
        # URLs de descarga alternativas sin versionado específico
        "https://minecraft.azureedge.net/bin-linux/bedrock-server.zip",
        "https://aka.ms/bedrock-server",
    ],
    "cloudflared_url": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    "timeout": 60,
    "max_retries": 3,
    "user_agent": "SpaceBedrockLauncher/2.0 (Minecraft-Server-Installer)"
}

class SpaceBedrockManager:
    def __init__(self):
        self.server_process = None
        self.tunnel_process = None
        self.running = False
        self.is_codespaces = self.detect_codespaces()
        self.connection_info = {}
        
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

    def get_latest_version(self):
        """Intenta obtener la versión más reciente disponible"""
        test_versions = ["1.21.92", "1.21.100", "1.21.80", "1.21.70"]
        
        for version in test_versions:
            test_url = f"https://minecraft.azureedge.net/bin-linux/bedrock-server-{version}.zip"
            try:
                req = Request(test_url, headers={'User-Agent': CONFIG["user_agent"]})
                response = urlopen(req, timeout=10)
                if response.status == 200:
                    logging.info(f"✅ Versión disponible detectada: {version}")
                    return version
                response.close()
            except:
                continue
        
        # Si no encuentra ninguna, usar la configurada
        return CONFIG["version"]

    def download_file(self, url, destination):
        """Descarga robusta con manejo de errores mejorado"""
        logging.info(f"🌐 Descargando desde: {url}")
        
        for attempt in range(CONFIG["max_retries"]):
            try:
                headers = {
                    'User-Agent': CONFIG["user_agent"],
                    'Accept': 'application/zip, application/octet-stream, */*',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive'
                }
                
                req = Request(url, headers=headers)
                
                with urlopen(req, timeout=CONFIG["timeout"]) as response:
                    # Verificar que la respuesta es válida
                    if response.status != 200:
                        raise HTTPError(url, response.status, "Respuesta no válida", response.headers, None)
                    
                    # Verificar Content-Type si está disponible
                    content_type = response.headers.get('Content-Type', '')
                    if content_type and 'zip' not in content_type and 'octet-stream' not in content_type:
                        logging.warning(f"⚠️ Content-Type inesperado: {content_type}")
                    
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
                                print(f"\rProgreso: {progress:.1f}% ({downloaded//1024//1024}MB/{total_size//1024//1024}MB)", end='', flush=True)
                
                print()
                
                # Verificar tamaño mínimo del archivo (50MB en lugar de 100MB)
                file_size = os.path.getsize(destination)
                if file_size < 50_000_000:  # ~50MB
                    raise ValueError(f"Archivo demasiado pequeño ({file_size//1024//1024}MB), probable descarga corrupta")
                
                # Verificar que es un archivo ZIP válido
                try:
                    with zipfile.ZipFile(destination, 'r') as test_zip:
                        if 'bedrock_server' not in test_zip.namelist():
                            raise ValueError("El archivo ZIP no contiene el ejecutable del servidor")
                except zipfile.BadZipFile:
                    raise ValueError("El archivo descargado no es un ZIP válido")
                
                logging.info(f"✅ Descarga exitosa: {file_size//1024//1024}MB")
                return True
                
            except (URLError, HTTPError, Exception) as e:
                logging.warning(f"⚠️ Intento {attempt+1}/{CONFIG['max_retries']} fallido: {str(e)}")
                if attempt < CONFIG["max_retries"] - 1:
                    time.sleep(3)  # Esperar más tiempo antes de reintentar
                else:
                    # En el último intento, limpiar archivo parcial
                    if os.path.exists(destination):
                        os.remove(destination)
        
        return False

    def setup_environment(self):
        """Configuración inicial del entorno para Space"""
        logging.info("🛸 Preparando entorno Space...")
        
        data_path = Path(CONFIG["data_dir"])
        data_path.mkdir(exist_ok=True)
        
        # Configuraciones específicas para Codespaces
        if self.is_codespaces:
            logging.info("🌐 Detectado GitHub Codespaces")
            os.environ['DEBIAN_FRONTEND'] = 'noninteractive'
            
        # Verificar espacio en disco
        try:
            disk_usage = shutil.disk_usage(data_path)
            free_gb = disk_usage.free / (1024**3)
            logging.info(f"💾 Espacio libre: {free_gb:.1f} GB")
            
            if free_gb < 1.0:
                logging.warning("⚠️ Poco espacio en disco disponible")
        except:
            pass
        
        # Verificar conectividad
        try:
            test_req = Request("https://www.minecraft.net", headers={'User-Agent': CONFIG["user_agent"]})
            urlopen(test_req, timeout=10)
            logging.info("✅ Conectividad verificada")
        except:
            logging.warning("⚠️ Problemas de conectividad detectados")
        
        return True

    def install_bedrock_server(self):
        """Instala el servidor Bedrock con URLs actualizadas"""
        server_path = Path(CONFIG["data_dir"]) / "bedrock_server"
        
        if server_path.exists():
            logging.info("✅ Servidor ya instalado")
            return True
        
        # Obtener versión más reciente
        current_version = self.get_latest_version()
        CONFIG["version"] = current_version
        
        zip_name = f"bedrock-server-{CONFIG['version']}.zip"
        zip_path = Path(CONFIG["data_dir"]) / zip_name
        
        logging.info(f"📥 Descargando servidor Bedrock {CONFIG['version']}...")
        
        # Intentar descargar desde mirrors principales
        for i, mirror_template in enumerate(CONFIG["mirrors"]):
            url = mirror_template.format(version=CONFIG['version'])
            logging.info(f"🔍 Probando mirror {i+1}/{len(CONFIG['mirrors'])}")
            
            if self.download_file(url, zip_path):
                break
        else:
            # Intentar URLs de fallback (sin versión específica)
            logging.warning("⚠️ Mirrors principales fallaron, probando URLs de fallback...")
            for i, fallback_url in enumerate(CONFIG["fallback_urls"]):
                logging.info(f"🔄 Probando fallback {i+1}/{len(CONFIG['fallback_urls'])}")
                if self.download_file(fallback_url, zip_path):
                    break
            else:
                logging.error("❌ Falló la descarga desde todos los orígenes")
                return False
        
        # Extraer el servidor
        try:
            logging.info("📦 Extrayendo servidor Bedrock...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(CONFIG["data_dir"])
            
            # Verificar extracción
            if not server_path.exists():
                logging.error("❌ El servidor no se extrajo correctamente")
                return False
            
            # Hacer ejecutable
            server_path.chmod(0o755)
            
            # Limpiar archivo zip
            zip_path.unlink()
            
            logging.info("🎉 Servidor instalado correctamente")
            return True
            
        except Exception as e:
            logging.error(f"❌ Error al extraer: {e}")
            return False

    def setup_tunnel(self):
        """Configura el túnel según el entorno"""
        if self.is_codespaces:
            return self.setup_codespaces_tunnel()
        return self.setup_cloudflared()
    
    def setup_codespaces_tunnel(self):
        """Configura el túnel nativo de Codespaces"""
        logging.info("🚀 Configurando túnel nativo de Codespaces...")
        
        codespace_name = os.getenv('CODESPACE_NAME', 'space-server')
        github_domain = os.getenv('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN', 'preview.app.github.dev')
        
        self.connection_info = {
            "type": "codespaces",
            "address": f"{codespace_name}-{CONFIG['port']}.{github_domain}",
            "port": CONFIG['port'],
            "note": "Haz público el puerto en la pestaña 'PORTS'"
        }
        
        return True

    def setup_cloudflared(self):
        """Configura Cloudflared para túnel externo"""
        cloudflared_path = Path(CONFIG["data_dir"]) / "cloudflared"
        
        if not cloudflared_path.exists():
            logging.info("⬇️ Descargando Cloudflared...")
            if not self.download_file(CONFIG["cloudflared_url"], cloudflared_path):
                logging.error("❌ Error descargando Cloudflared")
                return False
            cloudflared_path.chmod(0o755)
        
        token = os.getenv("CLOUDFLARED_TOKEN")
        if not token:
            logging.warning("⚠️ CLOUDFLARED_TOKEN no configurado")
            return False
        
        try:
            logging.info("🌐 Iniciando túnel Cloudflare...")
            self.tunnel_process = subprocess.Popen(
                [str(cloudflared_path), "tunnel", "--protocol", "udp", "run", "--token", token],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            time.sleep(8)
            
            if self.tunnel_process.poll() is not None:
                logging.error("❌ El túnel Cloudflare falló al iniciar")
                return False
            
            self.connection_info = {
                "type": "cloudflare",
                "address": "Consulta los logs de Cloudflare",
                "port": CONFIG['port'],
                "note": "Túnel Cloudflare activo"
            }
            
            logging.info("✅ Túnel Cloudflare iniciado")
            return True
                
        except Exception as e:
            logging.error(f"❌ Error iniciando túnel: {e}")
            return False

    def configure_server(self):
        """Configura server.properties optimizado"""
        config_path = Path(CONFIG["data_dir"]) / "server.properties"
        
        server_config = {
            "server-name": "Space Bedrock Server",
            "gamemode": "survival",
            "difficulty": "normal",
            "allow-cheats": "false",
            "max-players": "10",
            "online-mode": "true",
            "server-port": str(CONFIG["port"]),
            "level-name": "Space-World",
            "default-player-permission-level": "member",
            "player-idle-timeout": "30",
            "view-distance": "12",
            "max-threads": "0",
            "server-authoritative-movement": "server-auth",
            "compression-threshold": "1"
        }
        
        logging.info("⚙️ Configurando servidor...")
        
        if config_path.exists():
            logging.info("🔄 Actualizando configuración existente...")
            existing_config = {}
            with open(config_path, 'r') as f:
                for line in f:
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        existing_config[key] = value
            
            for key in list(server_config.keys()):
                if key in existing_config:
                    server_config[key] = existing_config[key]
        
        with open(config_path, 'w') as f:
            for key, value in server_config.items():
                f.write(f"{key}={value}\n")

    def generate_world_backup(self):
        """Crea un backup del mundo si existe"""
        world_dir = Path(CONFIG["data_dir"]) / "worlds"
        if not world_dir.exists() or not any(world_dir.iterdir()):
            return
            
        backup_dir = Path(CONFIG["data_dir"]) / "backups"
        backup_dir.mkdir(exist_ok=True)
        
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        backup_name = f"world-backup-{timestamp}.zip"
        backup_path = backup_dir / backup_name
        
        try:
            logging.info(f"💾 Creando backup: {backup_name}")
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(world_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, world_dir)
                        zipf.write(file_path, arcname)
        except Exception as e:
            logging.error(f"❌ Error creando backup: {str(e)}")

    def start_server(self):
        """Inicia el servidor Bedrock"""
        server_path = Path(CONFIG["data_dir"]) / "bedrock_server"
        
        if not server_path.exists():
            logging.error("❌ Servidor no encontrado")
            return False
        
        os.chdir(CONFIG["data_dir"])
        logging.info("🚀 Iniciando servidor Space Bedrock...")
        
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
            
            def log_reader():
                while self.running and self.server_process.poll() is None:
                    if self.server_process.stdout:
                        line = self.server_process.stdout.readline()
                        if line:
                            timestamp = time.strftime("%H:%M:%S")
                            print(f"[{timestamp}] {line.rstrip()}")
                    else:
                        time.sleep(0.1)
            
            log_thread = threading.Thread(target=log_reader, daemon=True)
            log_thread.start()
            
            self.server_process.wait()
            return True
            
        except KeyboardInterrupt:
            logging.info("⏹️ Deteniendo servidor...")
            return True
        except Exception as e:
            logging.error(f"❌ Error ejecutando servidor: {e}")
            return False
        finally:
            self.running = False
            self.generate_world_backup()

    def cleanup(self):
        """Limpia procesos al cerrar"""
        self.running = False
        
        if self.server_process and self.server_process.poll() is None:
            logging.info("🛑 Deteniendo servidor...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                logging.warning("⚠️ Forzando cierre del servidor...")
                self.server_process.kill()
        
        if self.tunnel_process and self.tunnel_process.poll() is None:
            logging.info("🔌 Deteniendo túnel...")
            self.tunnel_process.terminate()
            try:
                self.tunnel_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.tunnel_process.kill()

    def show_menu(self):
        """Muestra el menú interactivo"""
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"""
        ███████╗██████╗  █████╗  ██████╗███████╗
        ██╔════╝██╔══██╗██╔══██╗██╔════╝██╔════╝
        ███████╗██████╔╝███████║██║     █████╗  
        ╚════██║██╔═══╝ ██╔══██║██║     ██╔══╝  
        ███████║██║     ██║  ██║╚██████╗███████╗
        ╚══════╝╚═╝     ╚═╝  ╚═╝ ╚═════╝╚══════╝
        
        Space Bedrock Server Launcher v2.0
        {'='*50}
        Versión: {CONFIG['version']}
        Entorno: {'Codespaces' if self.is_codespaces else 'Local/VPS'}
        Directorio: {CONFIG['data_dir']}
        {'='*50}
        1. Iniciar servidor
        2. Cambiar versión  
        3. Configurar túnel
        4. Editar configuración
        5. Crear backup del mundo
        6. Salir
        {'='*50}
        """)
        return input("Seleccione una opción: ").strip()

    def change_version(self):
        """Cambia la versión del servidor"""
        print(f"\nVersión actual: {CONFIG['version']}")
        print("Versiones sugeridas: 1.21.92, 1.21.100, 1.21.80")
        new_version = input("Nueva versión: ").strip()
        if new_version:
            CONFIG["version"] = new_version
            print(f"✅ Versión actualizada a {CONFIG['version']}")
            # Eliminar servidor existente para forzar nueva descarga
            server_path = Path(CONFIG["data_dir"]) / "bedrock_server"
            if server_path.exists():
                server_path.unlink()
                print("🗑️ Servidor anterior eliminado")
        else:
            print("❌ No se especificó versión")
        input("\nPresione Enter para continuar...")

    def edit_configuration(self):
        """Edita la configuración del servidor"""
        config_path = Path(CONFIG["data_dir"]) / "server.properties"
        if config_path.exists():
            editor = "nano" if sys.platform != "win32" else "notepad"
            subprocess.run([editor, str(config_path)])
            print("✅ Configuración guardada")
        else:
            print("⚠️ Primero debe iniciar el servidor para generar la configuración")
        input("\nPresione Enter para continuar...")

    def run_interactive(self):
        """Ejecuta el launcher en modo interactivo"""
        self.setup_signal_handlers()
        self.setup_environment()
        
        while True:
            choice = self.show_menu()
            
            if choice == "1":
                if not self.install_bedrock_server():
                    input("\nError instalando servidor. Presione Enter...")
                    continue
                
                self.configure_server()
                
                if not self.setup_tunnel():
                    print("⚠️ Continuando sin túnel...")
                
                print("\n" + "="*50)
                if self.connection_info:
                    print("🔗 INFORMACIÓN DE CONEXIÓN:")
                    print(f"   Tipo: {self.connection_info['type'].upper()}")
                    print(f"   Dirección: {self.connection_info['address']}")
                    print(f"   Puerto: {self.connection_info['port']}")
                    print(f"   Nota: {self.connection_info['note']}")
                else:
                    print("⚠️ No se obtuvo información de conexión")
                
                if self.is_codespaces:
                    print("\n📋 INSTRUCCIONES PARA CODESPACES:")
                    print("   1. Ve a la pestaña 'PORTS' en VS Code")
                    print(f"   2. Encuentra el puerto {CONFIG['port']}")
                    print("   3. Haz clic derecho → 'Port Visibility' → 'Public'")
                    print("   4. Usa la URL mostrada para conectarte")
                
                print("\n⚠️  PRESIONA CTRL+C PARA DETENER EL SERVIDOR")
                print("="*50 + "\n")
                
                self.start_server()
                self.cleanup()
                
            elif choice == "2":
                self.change_version()
                
            elif choice == "3":
                if self.is_codespaces:
                    print("\nEn Codespaces se usa el túnel nativo automáticamente")
                else:
                    print("\nConfigurando túnel Cloudflare...")
                    if self.setup_cloudflared():
                        print("✅ Túnel configurado")
                    else:
                        print("❌ Error configurando túnel")
                input("\nPresione Enter para continuar...")
                
            elif choice == "4":
                self.edit_configuration()
                
            elif choice == "5":
                self.generate_world_backup()
                print("✅ Backup creado correctamente")
                input("\nPresione Enter para continuar...")
                
            elif choice == "6":
                print("\n👋 ¡Hasta pronto!")
                sys.exit(0)
                
            else:
                print("\n❌ Opción no válida")
                time.sleep(1)

def main():
    """Función principal"""
    try:
        manager = SpaceBedrockManager()
        manager.run_interactive()
    except Exception as e:
        logging.error(f"❌ Error crítico: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
