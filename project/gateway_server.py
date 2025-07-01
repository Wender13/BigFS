import grpc
from concurrent import futures
import os
import sys
import uuid
import bigfs_pb2
import bigfs_pb2_grpc

CHUNK_SIZE_BYTES = 1 * 1024 * 1024
METADATA_SERVER_ADDRESS = '127.0.0.1:50051'

class GatewayService(bigfs_pb2_grpc.GatewayServiceServicer):
    def __init__(self):
        self.metadata_channel = grpc.insecure_channel(METADATA_SERVER_ADDRESS)
        self.metadata_stub = bigfs_pb2_grpc.MetadataServiceStub(self.metadata_channel)
        self.temp_dir = "gateway_temp"
        if not os.path.exists(self.temp_dir): os.makedirs(self.temp_dir)

    def UploadFile(self, request_iterator, context):
        temp_filename = os.path.join(self.temp_dir, str(uuid.uuid4()))
        try:
            first_chunk = next(request_iterator)
            remote_path = first_chunk.metadata.remote_path
            file_size = 0
            with open(temp_filename, 'wb') as f:
                for chunk in request_iterator:
                    f.write(chunk.data); file_size += len(chunk.data)

            file_req = bigfs_pb2.FileRequest(filename=remote_path, size=file_size)
            write_plan = self.metadata_stub.GetWritePlan(file_req)
            if not write_plan.locations:
                raise Exception(context.details() or "Falha ao obter plano de escrita.")

            with open(temp_filename, 'rb') as f:
                for loc in write_plan.locations:
                    chunk_data = f.read(CHUNK_SIZE_BYTES)
                    with grpc.insecure_channel(loc.primary_node_id) as channel:
                        stub = bigfs_pb2_grpc.StorageServiceStub(channel)
                        chunk_msg = bigfs_pb2.Chunk(chunk_id=loc.chunk_id, data=chunk_data, replica_node_ids=loc.replica_node_ids)
                        stub.StoreChunk(chunk_msg)
            return bigfs_pb2.SimpleResponse(success=True)
        except Exception as e:
            context.set_details(str(e)); context.set_code(grpc.StatusCode.INTERNAL)
            return bigfs_pb2.SimpleResponse(success=False, message=str(e))
        finally:
            if os.path.exists(temp_filename): os.remove(temp_filename)

    def GetDownloadMap(self, request, context):
        return self.metadata_stub.GetFileLocation(request)

    def ListFiles(self, request, context):
        return self.metadata_stub.ListFiles(request)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    bigfs_pb2_grpc.add_GatewayServiceServicer_to_server(GatewayService(), server)
    server.add_insecure_port('[::]:50050'); server.start()
    print("📡 Gateway Server escutando na porta 50050.")
    server.wait_for_termination()

if __name__ == '__main__': serve()