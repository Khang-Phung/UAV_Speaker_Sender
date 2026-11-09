import socket
import threading


class TcpControl:
    """
    TCP client điều khiển. Không biết gì về state của ứng dụng,
    chỉ báo ra ngoài qua callback:
      on_message(text)  : server gửi dữ liệu
      on_disconnect()   : server đóng hoặc lỗi socket (không gọi khi tự close())
    Callback chạy trong thread nhận.
    """

    def __init__(self, on_message, on_disconnect):
        self._on_message = on_message
        self._on_disconnect = on_disconnect
        self._sock = None
        self._thread = None

    @property
    def connected(self):
        return self._sock is not None

    def connect_and_send(self, ip, port, message):
        # Đóng kết nối cũ nếu còn (thread cũ sẽ tự thoát vì socket đã đổi)
        self.close()

        try:
            sock = socket.create_connection((ip, port), timeout=2)
            sock.settimeout(1)
            self._sock = sock

            print(f"TCP connected: {ip}:{port}")

            sock.sendall(message.encode("utf-8"))
            print(f"TCP TX: {message}")

            # Mỗi kết nối có thread riêng, gắn với đúng socket của nó
            self._thread = threading.Thread(
                target=self._receive_task,
                args=(sock,),
                daemon=True
            )
            self._thread.start()
            print("TCP receive thread started")
            return True

        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            print(f"TCP send error: {e}")
            self.close()
            return False

    def _receive_task(self, sock):
        print("TCP RX task started")

        while self._sock is sock:
            try:
                data = sock.recv(512)

                if not data:
                    print("TCP server disconnected")
                    self._drop(sock)
                    self._on_disconnect()
                    break

                message = data.decode("utf-8", errors="ignore")
                print(f"TCP RX: [{message}]")
                self._on_message(message)

            except socket.timeout:
                continue

            except OSError as e:
                # close() chủ động -> self._sock đã đổi, thoát im lặng
                if self._sock is not sock:
                    break
                print(f"TCP receive error: {e}")
                self._drop(sock)
                self._on_disconnect()
                break

        print("TCP RX task stopped")

    def _drop(self, sock):
        if self._sock is sock:
            self._sock = None
        self._shutdown(sock)

    @staticmethod
    def _shutdown(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def close(self):
        sock, self._sock = self._sock, None
        if sock is not None:
            self._shutdown(sock)