import pandas as pd
import numpy as np
import sys
import os
import io
import json
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from sklearn.model_selection import train_test_split

import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

# ---------------------- SET SEED FOR REPRODUCIBILITY ----------------------
# SEED = 0
# np.random.seed(SEED)
# torch.manual_seed(SEED)
# --------------------------------------------------------------------------


server_data = pd.read_csv(r"C:\Users\alkou\Documents\GitHub\Scattered-Directive\house_energy_consumption\preprocessed_data\target.csv", delimiter=',')
print(server_data.head())

data = pd.read_csv(r"C:\Users\alkou\Documents\GitHub\Scattered-Directive\house_energy_consumption\preprocessed_data\scaled_data.csv", delimiter=',')

total_cols = data.shape[1]
# print(f"Total number of columns: {total_cols}")
cols_per_client = total_cols // 3
# print(f"Columns per client (approx): {cols_per_client}")

client1_data = data.iloc[:, :cols_per_client]
client2_data = data.iloc[:, cols_per_client : 2 * cols_per_client]
client3_data = data.iloc[:, 2 * cols_per_client:]

print(f"Client 1 data shape: {client1_data.shape}")
print(f"Client 2 data shape: {client2_data.shape}") 
print(f"Client 3 data shape: {client3_data.shape}")

# save data to file 
# client1_data.to_csv(r"C:\Users\alkou\Documents\GitHub\Scattered-Directive\python\vfl-train-demo\datasets\clientoneData.csv", index=False)
# client2_data.to_csv(r"C:\Users\alkou\Documents\GitHub\Scattered-Directive\python\vfl-train-demo\datasets\clienttwoData.csv", index=False)
# client3_data.to_csv(r"C:\Users\alkou\Documents\GitHub\Scattered-Directive\python\vfl-train-demo\datasets\clientthreeData.csv", index=False)

server_data.to_csv(r"C:\Users\alkou\Documents\GitHub\Scattered-Directive\python\vfl-train-model-demo\datasets\outcomeData.csv", index=False)


print(client1_data.head())
print(client2_data.head())
print(client3_data.head())


client_datasets = [client1_data, client2_data, client3_data]  
# client_datasets = [data]  

# sanity check that they have the same indices
client1_data.index.equals(server_data.index)

# # merge the three client datasets 
# merged = pd.concat([client1_data, client2_data, client3_data], axis=1)
# print(merged.head())
# print(merged.columns)
# client_datasets = [merged]

DEFAULT_NOF_CLIENTS = 3
REMOVE_CLIENT_ROUND = 60  # remove one client after these rounds
BACKTRACK = True  # if True, reinstantiate the server when a client is removed. Otherwise, keep the neurons the same, just fewer. Truncate the last neurons.

ADD_CLIENT_ROUND = 120  # add one client after these rounds
ADD_CLIENT_CLEAN = False  # if True, reinstantiate the added client. Otherwise, just keep the client the way it is. It might be pretrained already.

TOTAL_ROUNDS = 180
# with one client and one FC layer it takes about 2000 rounds to converge
# with one client and two FC layers it takes about 200 rounds to converge

SERVER_CHECKPOINT_PATH = "./server_state.pth"

LEARNING_RATE = 0.1
DEFAULT_LEARNING_RATE = 0.1

neurons_multiplier = 1

# # Dummy data loading (replace with your CSV)
# data = pd.read_csv("your_data.csv")  # should contain features for all clients + 'Survived' label

# # Simulate 3 clients, each with 4 features
# client_features = [
#     data.iloc[:, 0:4].values,   # Client 1: columns 0-3
#     data.iloc[:, 4:8].values,   # Client 2: columns 4-7
#     data.iloc[:, 8:12].values   # Client 3: columns 8-11
# ]
# labels = data["Survived"].values

np.set_printoptions(threshold=sys.maxsize)  # To print full numpy arrays

# note: to revert in production


class ClientModel(nn.Module):
    def __init__(self, input_size):
        super().__init__()
        # Layer 1: Input features -> Hidden layer (e.g., 64 neurons)
        print(f"Client model input size: {input_size}")
        self.fc1 = nn.Linear(input_size, 64*neurons_multiplier)
        # Layer 2: Hidden layer -> Output embedding (8 neurons)
        self.fc2 = nn.Linear(64*neurons_multiplier, 4*neurons_multiplier)
        self.dropout = nn.Dropout(p=0.5)

    def forward(self, x):
        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        x = self.fc2(x)
        return x

def serialise_array(array):
    return json.dumps([
        str(array.dtype),
        array.tobytes().decode("latin1"),
        array.shape])


def deserialise_array(string, hook=None):
    encoded_data = json.loads(string, object_pairs_hook=hook)
    # logger.info(string, encoded_data)
    dataType = np.dtype(encoded_data[0])
    dataArray = np.frombuffer(encoded_data[1].encode("latin1"), dataType)

    if len(encoded_data) > 2:
        return dataArray.reshape(encoded_data[2])

    return dataArray
 
class VFLClient():
    def __init__(self, data, learning_rate=LEARNING_RATE, model_state=None, optimiser_state=None):
        # self.data = torch.tensor(StandardScaler().fit_transform(data)).float()  # in this case the dataset is already scaled
        self.data = torch.tensor(data.values, dtype=torch.float32)
        
        self.model = ClientModel(data.shape[1])
        if model_state is not None:
            self.model.load_state_dict(model_state)

        self.optimiser = None

    def create_optimiser(self, learning_rate):
        if self.optimiser is None:
            self.optimiser = torch.optim.Adam(self.model.parameters(), lr=learning_rate, weight_decay=1e-4)   #  torch.optim.SGD(self.model.parameters(), lr=learning_rate)

    def train_model(self):
        self.embedding = self.model(self.data)
        ser_array = serialise_array(self.embedding.detach().numpy())
        print(f"size of serialized array in bytes: {sys.getsizeof(ser_array)}")
        return ser_array

    def gradient_descent(self, gradients):
        if self.optimiser is None:
            print("Optimiser is not defined.")
            pass 

        try:
            self.model.zero_grad()
            # embedding = self.model(self.data)
            self.embedding.backward(torch.from_numpy(gradients))
            self.optimiser.step()
        except Exception as e:
            print(f"Error occurred: {e}")



def shrink_server_model(old_model, new_input_size):
    """
    Creates a new ServerModel with fewer input neurons and copies over the trained weights
    from the old model for the first new_input_size neurons.
    """
    # Create the new model
    new_model = ServerModel(new_input_size)
    # Copy weights: old_model.fc.weight shape: [1, old_input_size]
    with torch.no_grad():
        # Take only first new_input_size columns (neurons)
        new_model.fc.weight[:, :] = old_model.fc.weight[:, :new_input_size]
        new_model.fc.bias[:] = old_model.fc.bias[:]
    return new_model


# class ServerModel(nn.Module):
#     def __init__(self, input_size):
#         super(ServerModel, self).__init__()
#         self.fc = nn.Linear(input_size, 1)

#     def forward(self, x):
#         x = self.fc(x)
#         return x

class ServerModel(nn.Module):
    def __init__(self, input_size):
        super(ServerModel, self).__init__()
        # The input size will be (4 features/embedding * 3 clients) = 12
        hidden_size = 16 # A small hidden layer is a good start

        # Layer 1: Takes the concatenated embeddings to a hidden representation
        self.fc1 = nn.Linear(input_size, hidden_size)
        # Layer 2: Maps the hidden representation to the final output
        self.fc2 = nn.Linear(hidden_size, 1)
        # Optional: Add dropout for regularization on the server as well
        # self.dropout = nn.Dropout(p=0.1)

    def forward(self, x):
        # Pass through the first layer, then apply ReLU activation
        x = F.relu(self.fc1(x))
        # Apply dropout
        # x = self.dropout(x)
        # Pass through the final layer to get the regression output
        x = self.fc2(x)
        return x


class VFLServer():
    def __init__(self, data):
        self.intermediate_neurons = 4  # Assuming each client outputs 4 features
        self.nof_clients = DEFAULT_NOF_CLIENTS
        self.model = ServerModel(self.intermediate_neurons * self.nof_clients) 
        # self.initial_parameters = ndarrays_to_parameters(
        #     [val.cpu().numpy()
        #      for _, val in server_configuration.model.state_dict().items()]
        # )
        self.optimizer = optim.Adam(self.model.parameters(), lr=DEFAULT_LEARNING_RATE, weight_decay=1e-4)  # optim.SGD(self.model.parameters(), lr=0.01)
        self.criterion = nn.MSELoss()
        self.labels = torch.tensor(
            data["REL_TOTALBTU"].values).float().unsqueeze(1)

    def shrink_server_model(self, new_nof_clients, backtrack):
        """
        Creates a new ServerModel with fewer input neurons and copies over the trained weights
        from the old model for the first new_input_size neurons.
        """
        if backtrack and new_nof_clients==2:  # for now hardcoded to work only when reducing size from 3 to 2 clients
            # save model state to file
            logger.info("Saving server state before shrinking...")
            self.save_state(SERVER_CHECKPOINT_PATH)
        self.nof_clients = new_nof_clients
        # Create the new model
        # note: this is a completely new model with random weights
        self.model = ServerModel(self.intermediate_neurons * new_nof_clients)
        self.optimizer = optim.Adam(self.model.parameters(), lr=DEFAULT_LEARNING_RATE, weight_decay=1e-4)  # optim.SGD(self.model.parameters(), lr=0.01)

    
    def expand_server_model(self, new_nof_clients, backtrack):
        """
        Creates a new ServerModel with fewer input neurons and copies over the trained weights
        from the old model for the first new_input_size neurons.
        """
        self.nof_clients = new_nof_clients
        if backtrack and self.nof_clients==3:  # for now hardcoded to work only for 3 clients
            # save model state to file
            self.model = ServerModel(self.nof_clients * self.intermediate_neurons)
            self.optimizer = optim.Adam(self.model.parameters(), lr=DEFAULT_LEARNING_RATE, weight_decay=1e-4)  # optim.SGD(self.model.parameters(), lr=0.01)
            logger.info("Loading previous server state...")
            self.load_state(SERVER_CHECKPOINT_PATH)
        else:
            # Create the new model
            # note: this is a completely new model with random weights
            self.model = ServerModel(self.nof_clients * self.intermediate_neurons)
            self.optimizer = optim.Adam(self.model.parameters(), lr=DEFAULT_LEARNING_RATE, weight_decay=1e-4)  # optim.SGD(self.model.parameters(), lr=0.01)
    
    def update_server_model_architecture(self, old_nof_clients, new_nof_clients, backtrack):
        if new_nof_clients == old_nof_clients:
            # No change needed
            logger.debug("Number of clients unchanged, no model architecture update needed.")
        
        if new_nof_clients < old_nof_clients:
            logger.info(f"Number of clients decreased from {old_nof_clients} to {new_nof_clients}, shrinking model.")
            self.shrink_server_model(new_nof_clients, backtrack)
        
        if new_nof_clients > old_nof_clients:
            logger.info(f"Number of clients increased from {old_nof_clients} to {new_nof_clients}, expanding model.")
            self.expand_server_model(new_nof_clients, backtrack)


    def aggregate_fit(self, results,backtrack=False):
        global server_configuration

        # infer the number of clients based on the data received
        new_nof_clients = len(results)
        if new_nof_clients != self.nof_clients:
            print(f"Number of clients in results: {new_nof_clients}")
            print(f"Current number of clients: {self.nof_clients}")
            logger.info(f"Number of clients {new_nof_clients} does not match expected {self.nof_clients}, updating server architecture...")
            # TODO: update the architecture of the model
            self.update_server_model_architecture(self.nof_clients, new_nof_clients, backtrack)


        try:
            embedding_results = [
                torch.from_numpy(embedding.copy())
                for embedding in results
            ]
        except Exception as e:
            logger.info(f"Converting the results to torch failed: {e}")

        try:
            embeddings_aggregated = torch.cat(embedding_results, dim=1)
            embedding_server = embeddings_aggregated.detach().requires_grad_()
            output = self.model(embedding_server)
            loss = self.criterion(output, self.labels)
            loss.backward()

            self.optimizer.step()
            self.optimizer.zero_grad()
        except Exception as e:
            logger.info(f"Running gradient descent failed: {e}")

        try:
            grads = embedding_server.grad.split([4]*self.nof_clients, dim=1)
            np_gradients = [serialise_array(grad.numpy()) for grad in grads]
        except Exception as e:
            logger.info(f"Converting the gradients failed: {e}")

        with torch.no_grad():
            output = self.model(embedding_server)

            mse = nn.MSELoss()(output, self.labels).item()
            rmse = torch.sqrt(torch.tensor(mse)).item()
            mae = nn.L1Loss()(output, self.labels).item()
            total_sum_of_squares = torch.sum((self.labels - self.labels.mean()) ** 2)
            residual_sum_of_squares = torch.sum((self.labels - output) ** 2)
            r2 = 1 - (residual_sum_of_squares / total_sum_of_squares)
            r2_score = r2.item()

            metrics = {
                "mse": mse,
                "rmse": rmse,
                "mae": mae,
                "r2": r2_score
            }
            # Example of printing the metrics
            # print(f"Regression Metrics - MSE: {mse:.4f}, RMSE: {rmse:.4f}, MAE: {mae:.4f}, R²: {r2_score:.4f}")
            pass 


        # data = Struct()
        # data.update({"accuracy": r2_score, "gradients": np_gradients})  # TODO: maybe try to rename the field
        data = []
        data.append({"r2": r2_score, "gradients": np_gradients})

        logger.info(f"R2 achieved: {r2_score}")

        return data
    
    def save_state(self, filepath):
        """Save the state dicts for both model and optimizer to disk."""
        torch.save({
            'model_state_dict': self.model.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict()
        }, filepath)
        print(f"Server state saved to {filepath}")

    def load_state(self, filepath):
        """Load the state dicts for both model and optimizer from disk."""
        state = torch.load(filepath)
        self.model.load_state_dict(state['model_state_dict'])
        self.optimizer.load_state_dict(state['optimizer_state_dict'])
        print(f"Server state loaded from {filepath}")


# define clients
all_clients = []
for client_data in client_datasets[:DEFAULT_NOF_CLIENTS]:
    client = VFLClient(client_data)
    all_clients.append(client)

clients = all_clients[:DEFAULT_NOF_CLIENTS] # the active clients

vfl_server = VFLServer(server_data)


train_results = []

# Training loop
for round in range(TOTAL_ROUNDS):

    print("--------------------------------------------------")
    print(f"Round {round+1}")
    if round == REMOVE_CLIENT_ROUND:
        if DEFAULT_NOF_CLIENTS > 1:
            DEFAULT_NOF_CLIENTS -= 1
            clients.pop()  # remove the last client
            print(f"Client removed. Number of clients is now {DEFAULT_NOF_CLIENTS}.")
        else:
            print("Cannot remove more clients.")

        # print("Saving server state before modification...")
        # vfl_server.save_state(SERVER_CHECKPOINT_PATH)

        print("server resize should happen automatically now")

        # if SHRINK_SERVER:
        #     print(f"Shrinking server model for {DEFAULT_NOF_CLIENTS}...")
        #     # Shrink the server model to match the new number of clients
        #     old_model = vfl_server.model
        #     # Each client outputs 4 features
        #     vfl_server.model = shrink_server_model(old_model, 4*DEFAULT_NOF_CLIENTS*neurons_multiplier)
        # else:
        #     print(f"Reinstantiating server for {DEFAULT_NOF_CLIENTS}...")
        #     vfl_server = VFLServer(server_data)
        
        

    if round == ADD_CLIENT_ROUND:
        if DEFAULT_NOF_CLIENTS < 3:
            DEFAULT_NOF_CLIENTS += 1
            
            if ADD_CLIENT_CLEAN:
                print(f"Reinstantiating client {DEFAULT_NOF_CLIENTS-1}")
                all_clients[DEFAULT_NOF_CLIENTS-1] = VFLClient(client_datasets[DEFAULT_NOF_CLIENTS-1])  # reinstantiate the client

            clients.append(all_clients[DEFAULT_NOF_CLIENTS-1])  # add the next client
            print(f"Client added. Number of clients is now {DEFAULT_NOF_CLIENTS}.")
        else:
            print("Cannot add more clients.")

        
        # if os.path.isfile(SERVER_CHECKPOINT_PATH):
        #     print("Loading server state before modification...")
        #     vfl_server = VFLServer(server_data)  # clean server with the correct input size
        #     vfl_server.load_state(SERVER_CHECKPOINT_PATH)
        # else:
        #     print(f"Reinstantiating server for {DEFAULT_NOF_CLIENTS}...")
        #     vfl_server = VFLServer(server_data)

    #  1. Clients compute embeddings

    results = []
    for client in clients:
        results.append(client.train_model())

    # deserialise_array(embeddings[2])
    deserialized_results = [deserialise_array(embedding) for embedding in results]

    # 2. Server aggregates embeddings and returns accuracy and gradients
    data = vfl_server.aggregate_fit(deserialized_results, backtrack=BACKTRACK)

    # print(data[-1].keys())
    # print(data[-1]['r2'])

    gradients = data[-1]['gradients']

    # 3. backpropagate gradients to clients

    for i, vfl_client in enumerate(clients):
        vfl_client.create_optimiser(0.05)

        vfl_client.gradient_descent(deserialise_array(gradients[i]))
    

    train_results.append({
        "timestamp": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "train_round": round+1,
        "accuracy": data[-1]['r2'],
        "clients": DEFAULT_NOF_CLIENTS
    })

payload = {
    "metadata": {
        "total_rounds": TOTAL_ROUNDS,
        "REMOVE_CLIENT_ROUND": REMOVE_CLIENT_ROUND,
        "BACKTRACK": BACKTRACK,
        "ADD_CLIENT_ROUND": ADD_CLIENT_ROUND,
        "ADD_CLIENT_CLEAN": ADD_CLIENT_CLEAN,
    },
    "results": train_results
}

filename = f"./run_dumps/house_energy_vfl_test_results_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.json"
print(f"Saving to file {filename}")
with open(filename, "w") as f:
    json.dump(payload, f, indent=2)