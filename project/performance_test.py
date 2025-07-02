import grpc
import time
import threading
import concurrent.futures
import os
import sys
import random
import string
import statistics
from dataclasses import dataclass
from typing import List, Dict, Any
import bigfs_pb2
import bigfs_pb2_grpc

@dataclass
class TestResult:
    operation: str
    file_size_mb: float
    duration_seconds: float
    throughput_mbps: float
    success: bool
    error_message: str = ""

@dataclass
class TestConfig:
    gateway_address: str = "localhost:50050"
    test_duration_seconds: int = 60
    concurrent_clients: int = 5
    file_sizes_mb: List[float] = None
    test_files_dir: str = "test_files"
    
    def __post_init__(self):
        if self.file_sizes_mb is None:
            self.file_sizes_mb = [0.1, 1.0, 5.0, 10.0, 50.0]

class BigFSPerformanceTester:
    def __init__(self, config: TestConfig):
        self.config = config
        self.results: List[TestResult] = []
        self.test_files = {}
        self._setup_test_environment()
    
    def _setup_test_environment(self):
        """Prepara ambiente de teste criando arquivos de diferentes tamanhos"""
        if not os.path.exists(self.config.test_files_dir):
            os.makedirs(self.config.test_files_dir)
        
        print("🔧 Preparando arquivos de teste...")
        for size_mb in self.config.file_sizes_mb:
            filename = f"test_file_{size_mb}MB.dat"
            filepath = os.path.join(self.config.test_files_dir, filename)
            
            if not os.path.exists(filepath):
                self._create_test_file(filepath, size_mb)
            
            self.test_files[size_mb] = filepath
        print(f"✅ {len(self.test_files)} arquivos de teste preparados")
    
    def _create_test_file(self, filepath: str, size_mb: float):
        """Cria arquivo de teste com tamanho específico"""
        size_bytes = int(size_mb * 1024 * 1024)
        chunk_size = 64 * 1024  # 64KB chunks para criação eficiente
        
        with open(filepath, 'wb') as f:
            remaining = size_bytes
            while remaining > 0:
                chunk = os.urandom(min(chunk_size, remaining))
                f.write(chunk)
                remaining -= len(chunk)
    
    def _get_client(self):
        """Cria cliente BigFS conectado ao gateway"""
        try:
            channel = grpc.insecure_channel(self.config.gateway_address)
            grpc.channel_ready_future(channel).result(timeout=5)
            return bigfs_pb2_grpc.GatewayServiceStub(channel), channel
        except grpc.FutureTimeoutError:
            raise ConnectionError(f"Não foi possível conectar ao gateway em {self.config.gateway_address}")
    
    def _upload_file(self, local_path: str, remote_path: str) -> TestResult:
        """Testa upload de arquivo individual"""
        file_size_mb = os.path.getsize(local_path) / (1024 * 1024)
        start_time = time.time()
        
        try:
            stub, channel = self._get_client()
            
            def upload_generator():
                yield bigfs_pb2.ChunkUploadRequest(
                    metadata=bigfs_pb2.FileMetadata(remote_path=remote_path)
                )
                with open(local_path, 'rb') as f:
                    while True:
                        data = f.read(1024 * 1024)  # 1MB chunks
                        if not data:
                            break
                        yield bigfs_pb2.ChunkUploadRequest(data=data)
            
            response = stub.UploadFile(upload_generator())
            duration = time.time() - start_time
            
            if response.success:
                throughput_mbps = file_size_mb / duration if duration > 0 else 0
                return TestResult("upload", file_size_mb, duration, throughput_mbps, True)
            else:
                return TestResult("upload", file_size_mb, duration, 0, False, response.message)
        
        except Exception as e:
            duration = time.time() - start_time
            return TestResult("upload", file_size_mb, duration, 0, False, str(e))
        finally:
            try:
                channel.close()
            except:
                pass
    
    def _download_file(self, remote_path: str, local_path: str) -> TestResult:
        """Testa download de arquivo individual"""
        start_time = time.time()
        file_size_mb = 0
        
        try:
            stub, channel = self._get_client()
            
            file_req = bigfs_pb2.FileRequest(filename=remote_path)
            response_stream = stub.DownloadFile(file_req)
            
            with open(local_path, 'wb') as f:
                for chunk_response in response_stream:
                    f.write(chunk_response.data)
                    file_size_mb += len(chunk_response.data) / (1024 * 1024)
                    
                    if chunk_response.is_final_chunk:
                        break
            
            duration = time.time() - start_time
            throughput_mbps = file_size_mb / duration if duration > 0 else 0
            return TestResult("download", file_size_mb, duration, throughput_mbps, True)
        
        except Exception as e:
            duration = time.time() - start_time
            return TestResult("download", file_size_mb, duration, 0, False, str(e))
        finally:
            try:
                channel.close()
            except:
                pass
    
    def _list_files(self) -> TestResult:
        """Testa operação de listagem de arquivos"""
        start_time = time.time()
        
        try:
            stub, channel = self._get_client()
            
            response = stub.ListFiles(bigfs_pb2.PathRequest(path=""))
            duration = time.time() - start_time
            
            file_count = len(response.files)
            throughput_mbps = file_count / duration if duration > 0 else 0
            
            return TestResult("list", file_count, duration, throughput_mbps, True)
        
        except Exception as e:
            duration = time.time() - start_time
            return TestResult("list", 0, duration, 0, False, str(e))
        finally:
            try:
                channel.close()
            except:
                pass
    
    def _remove_file(self, remote_path: str) -> TestResult:
        """Testa remoção de arquivo"""
        start_time = time.time()
        
        try:
            stub, channel = self._get_client()
            
            file_req = bigfs_pb2.FileRequest(filename=remote_path)
            response = stub.RemoveFile(file_req)
            duration = time.time() - start_time
            
            if response.success:
                throughput_mbps = 1/duration if duration > 0 else 0
                return TestResult("remove", 0, duration, throughput_mbps, True)
            else:
                return TestResult("remove", 0, duration, 0, False, response.message)
        
        except Exception as e:
            duration = time.time() - start_time
            return TestResult("remove", 0, duration, 0, False, str(e))
        finally:
            try:
                channel.close()
            except:
                pass
    
    def test_sequential_operations(self):
        """Teste sequencial de operações básicas"""
        print("\n📊 TESTE SEQUENCIAL DE OPERAÇÕES")
        print("=" * 50)
        
        for size_mb in self.config.file_sizes_mb:
            local_file = self.test_files[size_mb]
            remote_file = f"perf_test_{size_mb}MB_{int(time.time())}.dat"
            download_file = f"downloaded_{remote_file}"
            
            print(f"\n🔄 Testando arquivo de {size_mb}MB...")
            
            # Upload
            result = self._upload_file(local_file, remote_file)
            if result.success:
                print(f"  ⬆️  Upload: {result.throughput_mbps:.2f} MB/s ({result.duration_seconds:.2f}s)")
            else:
                print(f"  ❌ Upload falhou: {result.error_message}")
                continue
            
            # Download
            result = self._download_file(remote_file, download_file)
            self.results.append(result)
            if result.success:
                print(f"  ⬇️  Download: {result.throughput_mbps:.2f} MB/s ({result.duration_seconds:.2f}s)")
            else:
                print(f"  ❌ Download falhou: {result.error_message}")
                print(f"  ❌ Download falhou: {result.error_message}")
            
            # Cleanup
            if os.path.exists(download_file):
                os.remove(download_file)
            
            self._remove_file(remote_file)
    
    def test_concurrent_uploads(self):
        """Teste de uploads concorrentes para avaliar escalabilidade"""
        print(f"\n📊 TESTE DE UPLOADS CONCORRENTES ({self.config.concurrent_clients} clientes)")
        print("=" * 60)
        
        def worker_upload(worker_id: int, size_mb: float):
            local_file = self.test_files[size_mb]
            remote_file = f"concurrent_upload_{worker_id}_{size_mb}MB_{int(time.time())}.dat"
            
            result = self._upload_file(local_file, remote_file)
            self.results.append(result)
            if result.success:
                print(f"  Worker {worker_id}: {result.throughput_mbps:.2f} MB/s")
            else:
                print(f"  Worker {worker_id}: FALHA - {result.error_message}")
                print(f"  Worker {worker_id}: FALHA - {result.error_message}")
            
            # Cleanup
            self._remove_file(remote_file)
            return result
        
        for size_mb in [1.0, 5.0]:  # Testa com arquivos médios
            print(f"\n🔄 Uploads concorrentes de arquivos {size_mb}MB...")
            
            start_time = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.concurrent_clients) as executor:
                futures = [
                    executor.submit(worker_upload, i, size_mb)
                    for i in range(self.config.concurrent_clients)
                ]
                
                results = [f.result() for f in concurrent.futures.as_completed(futures)]
            
            total_time = time.time() - start_time
            successful_results = [r for r in results if r.success]
            
            total_throughput = sum(r.throughput_mbps for r in successful_results)
            avg_throughput = statistics.mean([r.throughput_mbps for r in successful_results])
            
            print(f"  📈 Throughput agregado: {total_throughput:.2f} MB/s")
            print(f"  📊 Throughput médio por cliente: {avg_throughput:.2f} MB/s")
            print(f"  ⏱️  Tempo total: {total_time:.2f}s")
            print(f"  ✅ Sucessos: {len(successful_results)}/{len(results)}")
            print(f"  ✅ Sucessos: {len(successful_results)}/{len(results)}")
    
    def test_mixed_workload(self):
        """Teste de carga mista simulando uso real"""
        print(f"\n📊 TESTE DE CARGA MISTA ({self.config.test_duration_seconds}s)")
        print("=" * 50)
        
        operations = ['upload', 'download', 'list']
        weights = [0.4, 0.4, 0.2]  # 40% upload, 40% download, 20% list
        
        def worker_mixed_load(worker_id: int):
            worker_results = []
            end_time = time.time() + self.config.test_duration_seconds
            
            uploaded_files = []
            
            while time.time() < end_time:
                operation = random.choices(operations, weights=weights)[0]
                
                if operation == 'upload':
                    size_mb = random.choice(self.config.file_sizes_mb)
                    local_file = self.test_files[size_mb]
                    remote_file = f"mixed_load_{worker_id}_{int(time.time())}_{random.randint(1000,9999)}.dat"
                    
                    result = self._upload_file(local_file, remote_file)
                    if result.success:
                        uploaded_files.append(remote_file)
                    worker_results.append(result)
                
                elif operation == 'download' and uploaded_files:
                    remote_file = random.choice(uploaded_files)
                    local_file = f"temp_download_{worker_id}_{int(time.time())}.dat"
                    
                    result = self._download_file(remote_file, local_file)
                    worker_results.append(result)
                    
                    if os.path.exists(local_file):
                        os.remove(local_file)
                
                elif operation == 'list':
                    result = self._list_files()
                    worker_results.append(result)
                
                time.sleep(random.uniform(0.1, 0.5))  # Simula pausa entre operações
            
            # Cleanup
            for remote_file in uploaded_files:
                self._remove_file(remote_file)
            
            return worker_results
        
        start_time = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.concurrent_clients) as executor:
            futures = [
                executor.submit(worker_mixed_load, i)
                for i in range(self.config.concurrent_clients)
            ]
            
            all_results = []
            for f in concurrent.futures.as_completed(futures):
                all_results.extend(f.result())
        
        total_time = time.time() - start_time
        
        # Análise dos resultados
        for operation in operations:
            op_results = [r for r in all_results if r.operation == operation and r.success]
            
            if op_results:
                total_ops = len(op_results)
                avg_duration = statistics.mean([r.duration_seconds for r in op_results])
                avg_throughput = statistics.mean([r.throughput_mbps for r in op_results])
                ops_per_sec = total_ops / total_time
                
                print(f"\n  📊 {operation.upper()}:")
                print(f"    Total de operações: {total_ops}")
                print(f"    Operações/segundo: {ops_per_sec:.2f}")
                print(f"    Latência média: {avg_duration:.3f}s")
                if operation in ['upload', 'download']:
                    print(f"    Throughput médio: {avg_throughput:.2f} MB/s")
        
        self.results.extend(all_results)
    
    def test_fault_tolerance(self):
        """Teste básico de tolerância a falhas"""
        print("\n📊 TESTE DE TOLERÂNCIA A FALHAS")
        print("=" * 40)
        
        # Simula cenário onde alguns downloads podem falhar
        print("🔄 Testando resiliência do sistema...")
        
        # Upload arquivo para teste
        size_mb = 5.0
        local_file = self.test_files[size_mb]
        remote_file = f"fault_test_{int(time.time())}.dat"
        
        upload_result = self._upload_file(local_file, remote_file)
        if not upload_result.success:
            print("❌ Falha no upload inicial, pulando teste de tolerância")
            return
        
        # Múltiplos downloads simultâneos para stressar o sistema
        def stress_download(attempt_id):
            local_file = f"stress_download_{attempt_id}.dat"
            result = self._download_file(remote_file, local_file)
            if os.path.exists(local_file):
                os.remove(local_file)
            return result
        
        print("  Executando downloads simultâneos...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(stress_download, i) for i in range(20)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        successful = len([r for r in results if r.success])
        failed = len(results) - successful
        
        print(f"  ✅ Downloads bem-sucedidos: {successful}/20")
        print(f"  ❌ Downloads falharam: {failed}/20")
        print(f"  📊 Taxa de sucesso: {(successful/20)*100:.1f}%")
        
        # Cleanup
        self._remove_file(remote_file)
        self.results.extend(results)
    
    def generate_report(self):
        """Gera relatório final de desempenho"""
        print("\n" + "=" * 80)
        print("📋 RELATÓRIO FINAL DE DESEMPENHO")
        print("=" * 80)
        
        if not self.results:
            print("❌ Nenhum resultado disponível")
            return
        
        # Estatísticas por operação
        operations = {}
        for result in self.results:
            if result.operation not in operations:
                operations[result.operation] = []
            operations[result.operation].append(result)
        
        for op_name, op_results in operations.items():
            successful = [r for r in op_results if r.success]
            failed = [r for r in op_results if not r.success]
            
            print(f"\n📊 {op_name.upper()}:")
            print(f"  Total de operações: {len(op_results)}")
            print(f"  Sucessos: {len(successful)} ({(len(successful)/len(op_results)*100):.1f}%)")
            print(f"  Falhas: {len(failed)}")
            
            if successful:
                durations = [r.duration_seconds for r in successful]
                throughputs = [r.throughput_mbps for r in successful if r.throughput_mbps > 0]
                
                print(f"  Latência média: {statistics.mean(durations):.3f}s")
                print(f"  Latência mediana: {statistics.median(durations):.3f}s")
                if len(durations) > 1:
                    print(f"  Desvio padrão latência: {statistics.stdev(durations):.3f}s")
                
                if throughputs:
                    print(f"  Throughput médio: {statistics.mean(throughputs):.2f} MB/s")
                    print(f"  Throughput máximo: {max(throughputs):.2f} MB/s")
                    print(f"  Throughput mínimo: {min(throughputs):.2f} MB/s")
        
        # Resumo geral
        total_ops = len(self.results)
        total_successful = len([r for r in self.results if r.success])
        overall_success_rate = (total_successful / total_ops * 100) if total_ops > 0 else 0
        
        print(f"\n🎯 RESUMO GERAL:")
        print(f"  Total de operações testadas: {total_ops}")
        print(f"  Taxa de sucesso geral: {overall_success_rate:.1f}%")
        
        # Recomendações
        print(f"\n💡 RECOMENDAÇÕES:")
        upload_results = [r for r in self.results if r.operation == 'upload' and r.success]
        if upload_results:
            avg_upload_throughput = statistics.mean([r.throughput_mbps for r in upload_results])
            if avg_upload_throughput < 10:
                print("  - Throughput de upload baixo. Considere otimizar tamanho de chunks ou paralelismo")
            if overall_success_rate < 95:
                print("  - Taxa de erro alta. Verifique estabilidade da rede e nós de storage")
        
        print("\n✅ Teste de desempenho concluído!")

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 performance_test.py <gateway_address> [duration] [clients]")
        print("Exemplo: python3 performance_test.py localhost:50050 120 8")
        sys.exit(1)
    
    config = TestConfig(
        gateway_address=sys.argv[1],
        test_duration_seconds=int(sys.argv[2]) if len(sys.argv) > 2 else 60,
        concurrent_clients=int(sys.argv[3]) if len(sys.argv) > 3 else 5
    )
    
    print("🚀 INICIANDO TESTE DE DESEMPENHO BIGFS")
    print(f"Gateway: {config.gateway_address}")
    print(f"Duração: {config.test_duration_seconds}s")
    print(f"Clientes concorrentes: {config.concurrent_clients}")
    
    tester = BigFSPerformanceTester(config)
    
    try:
        # Executa bateria de testes
        tester.test_sequential_operations()
        tester.test_concurrent_uploads()
        tester.test_mixed_workload()
        tester.test_fault_tolerance()
        
        # Gera relatório
        tester.generate_report()
        
    except KeyboardInterrupt:
        print("\n⚠️ Teste interrompido pelo usuário")
    except Exception as e:
        print(f"\n❌ Erro durante o teste: {e}")
    finally:
        # Cleanup
        if os.path.exists(config.test_files_dir):
            for file in os.listdir(config.test_files_dir):
                try:
                    os.remove(os.path.join(config.test_files_dir, file))
                except:
                    pass

if __name__ == '__main__':
    main()