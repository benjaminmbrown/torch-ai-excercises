package ai.torch.nexus.connector;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.openfeign.EnableFeignClients;

@SpringBootApplication
@EnableFeignClients
public class IntelConnectorApplication {
    public static void main(String[] args) {
        SpringApplication.run(IntelConnectorApplication.class, args);
    }
}
